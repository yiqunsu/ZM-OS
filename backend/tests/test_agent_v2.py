"""Durable transport and worker invariants, using real PostgreSQL transactions."""

import asyncio
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.worker import LeaseLost, RunResult, Worker, append_delta, claim, expire_runs, finalize
from app.core.config import settings
from app.models import (
    AgentFileGcJob,
    AgentRun,
    ChatAttachment,
    ChatMessage,
    ChatSession,
    OrderIntakeItem,
    SessionEvent,
)
from app.routers.agent_v2 import stream_events
from app.schemas.agent import CreateSession, SendMessage
from app.services import agent_gc_service as gc
from app.services import agent_query_service as queries
from app.services import agent_session_service as service
from tests.conftest import TEST_DB_URL


@pytest.fixture(autouse=True)
def enable_v2(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AGENT_V2_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))


async def create(client, kind="SCHEDULING", key=None):
    response = await client.post(
        "/api/agent/v2/sessions", json={"agent_type": kind}, headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code == 201, response.text
    return response.json()["session"]


def body(revision=1, **kwargs):
    return {
        "client_message_id": str(uuid4()),
        "content": "请帮我排单",
        "expected_state_revision": revision,
        **kwargs,
    }


async def upload(client, sid, key=None):
    output = io.BytesIO()
    Image.new("RGB", (4, 3)).save(output, format="PNG")
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/attachments",
        data={"client_upload_id": key or str(uuid4())},
        files={"file": ("order.png", output.getvalue(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_message_atomic_and_idempotent(client, db_session):
    key = str(uuid4())
    session = await create(client, key=key)
    assert (await create(client, key=key))["id"] == session["id"]
    sid = session["id"]
    request = body()
    first = await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=request)
    assert first.status_code == 202, first.text
    second = await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=request)
    assert second.json()["message_id"] == first.json()["message_id"]
    conflicting = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages", json={**request, "content": "changed"}
    )
    assert conflicting.status_code == 409
    busy = await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=body(2))
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "SESSION_BUSY"
    messages = (await db_session.scalars(select(ChatMessage).where(ChatMessage.session_id == sid))).all()
    assert len(messages) == 1
    event = await db_session.scalar(select(SessionEvent).where(SessionEvent.message_id == messages[0].id))
    assert event.payload["text"] == messages[0].content
    assert event.seq == messages[0].event_seq
    assert (
        await db_session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.session_id == sid))
        == 1
    )


@pytest.mark.asyncio
async def test_isolation_scope_and_validation(client, db_session):
    session = await create(client)
    other = ChatSession(user_id=None, title="unowned")
    db_session.add(other)
    await db_session.commit()
    assert (await client.get(f"/api/agent/v2/sessions/{other.id}/snapshot")).status_code == 404
    rejected = await client.post(
        f'/api/agent/v2/sessions/{session["id"]}/messages', json=body(attachment_ids=["unknown"])
    )
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "IMAGE_NOT_ALLOWED"
    assert (
        await client.post(
            "/api/agent/v2/sessions", json={"agent_type": "LEGACY"}, headers={"Idempotency-Key": "legacy"}
        )
    ).status_code == 422
    assert (
        await client.post(f'/api/agent/v2/sessions/{session["id"]}/messages', json=body(role="system"))
    ).status_code == 422
    # No old protocol can execute, inspect or delete a new typed session.
    assert (
        await client.post("/api/agent/chat", json={"session_id": session["id"], "content": "hello"})
    ).status_code == 404
    assert (await client.delete(f'/api/agent/sessions/{session["id"]}')).status_code == 404


@pytest.mark.asyncio
async def test_multi_image_queue_and_failed_binding_rolls_back(client, db_session):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    images = [await upload(client, sid) for _ in range(3)]
    invalid = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages",
        json=body(content="", attachment_ids=[images[0]["id"], "missing"]),
    )
    assert invalid.status_code == 404
    assert (await db_session.get(ChatAttachment, images[0]["id"])).status == "STAGED"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == sid)
        )
        == 0
    )
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages",
        json=body(content="", attachment_ids=[image["id"] for image in images]),
    )
    assert response.status_code == 202, response.text
    items = (
        await db_session.scalars(
            select(OrderIntakeItem)
            .where(OrderIntakeItem.session_id == sid)
            .order_by(OrderIntakeItem.queue_position)
        )
    ).all()
    assert [item.status for item in items] == ["ACTIVE", "PENDING", "PENDING"]
    assert all(item.recognition_status == "NOT_STARTED" for item in items)
    context = await claim(db_session, "test")
    await finalize(db_session, context, RunResult("请核对第一张"))
    fourth = await upload(client, sid)
    session = await db_session.get(ChatSession, sid)
    original = items[0].draft
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages",
        json=body(session.state_revision, content="追加", attachment_ids=[fourth["id"]]),
    )
    assert response.status_code == 202, response.text
    run = await db_session.get(AgentRun, response.json()["run_id"])
    assert run.config_snapshot["queued_only"] and run.work_item_id is None
    assert items[0].draft == original and session.active_work_item_id == items[0].id


@pytest.mark.asyncio
async def test_worker_failure_fences_and_retry_keeps_input(client, db_session):
    sid = (await create(client))["id"]
    accepted = (await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=body())).json()
    context = await claim(db_session, "worker")
    await append_delta(db_session, context, "未完成内容", 0)
    run = await db_session.get(AgentRun, context.run_id)
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await expire_runs(db_session) == 1
    with pytest.raises(LeaseLost):
        await finalize(db_session, context, RunResult("迟到的回复"))
    await db_session.rollback()
    snapshot = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert snapshot["active_run"] is None
    assert snapshot["recent_run_results"][0]["error_code"] == "WORKER_LOST"
    assert len(snapshot["messages"]) == 1
    key = str(uuid4())
    args = {
        "json": {"expected_state_revision": snapshot["session"]["state_revision"]},
        "headers": {"Idempotency-Key": key},
    }
    response = await client.post(f"/api/agent/v2/runs/{context.run_id}/retry", **args)
    assert response.status_code == 202, response.text
    repeated = await client.post(f"/api/agent/v2/runs/{context.run_id}/retry", **args)
    assert repeated.json() == response.json()
    assert response.json()["run"]["trigger_message_id"] == accepted["message_id"]
    assert response.json()["run"]["id"] != context.run_id


@pytest.mark.asyncio
async def test_events_reconnect_and_final_snapshot(client, db_session):
    sid = (await create(client))["id"]
    await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=body())
    context = await claim(db_session, "worker")
    await append_delta(db_session, context, "建议", 0)
    mid = await finalize(db_session, context, RunResult("建议已准备"))
    page = (await client.get(f"/api/agent/v2/sessions/{sid}/events?after=0")).json()
    assert [e["seq"] for e in page["events"]] == list(range(1, page["cursor"] + 1))
    final = [e for e in page["events"] if e["kind"] == "message.completed"][0]
    assert final["message_id"] == mid and final["payload"]["text"] == "建议已准备"
    replay = (await client.get(f"/api/agent/v2/sessions/{sid}/events?after={final['seq']}")).json()
    assert all(e["seq"] > final["seq"] for e in replay["events"])
    assert not any(e["kind"] == "assistant.delta" for e in replay["events"])


@pytest.mark.asyncio
async def test_delete_cancels_and_gc_retries(client, db_session, monkeypatch):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    await client.post(
        f"/api/agent/v2/sessions/{sid}/messages", json=body(content="", attachment_ids=[image["id"]])
    )
    context = await claim(db_session, "worker")
    args = {"headers": {"Idempotency-Key": str(uuid4())}}
    deleted = await client.delete(f"/api/agent/v2/sessions/{sid}", **args)
    assert deleted.status_code == 202
    assert (await client.delete(f"/api/agent/v2/sessions/{sid}", **args)).json() == deleted.json()
    assert (await client.get(f"/api/agent/v2/attachments/{image['id']}/content")).status_code == 410
    with pytest.raises(LeaseLost):
        await finalize(db_session, context, RunResult("late"))
    await db_session.rollback()
    real_delete = gc._delete_file

    def unavailable(_):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(gc, "_delete_file", unavailable)
    assert await gc.collect_once(db_session)
    assert await gc.finish_deletions(db_session) == 0
    job = await db_session.scalar(select(AgentFileGcJob).where(AgentFileGcJob.session_id == sid))
    assert job.last_error_code == "FILE_DELETE_FAILED"
    job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    monkeypatch.setattr(gc, "_delete_file", real_delete)
    assert await gc.collect_once(db_session)
    assert await gc.finish_deletions(db_session) == 1
    assert (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).status_code == 404
    assert (
        await db_session.scalar(
            select(func.count()).select_from(SessionEvent).where(SessionEvent.session_id == sid)
        )
        == 0
    )


@pytest_asyncio.fixture
async def independent_sessions():
    engine = create_async_engine(TEST_DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with factory() as db:
        sessions = (
            await db.scalars(select(ChatSession).where(ChatSession.title == "concurrency-test"))
        ).all()
        for session in sessions:
            session.active_work_item_id = None
        await db.flush()
        for session in sessions:
            from sqlalchemy import delete

            await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_acceptance_and_worker_claim(independent_sessions):
    factory = independent_sessions
    async with factory() as db:
        sid = (
            await service.create_session(
                db,
                "test-user",
                str(uuid4()),
                CreateSession(agent_type="SCHEDULING", title="concurrency-test"),
            )
        )["session"]["id"]
    barrier = asyncio.Barrier(2)

    async def send():
        async with factory() as db:
            await barrier.wait()
            try:
                return await service.accept_message(db, sid, "test-user", SendMessage(**body()))
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code

    results = await asyncio.gather(send(), send())
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results

    async def take():
        async with factory() as db:
            return await claim(db, str(uuid4()))

    contexts = await asyncio.gather(take(), take())
    assert sum(context is not None for context in contexts) == 1
    context = next(c for c in contexts if c)
    # Disconnecting a subscriber does not cancel the separately owned Run.
    async with factory() as db:
        stream = stream_events(db, sid, "test-user", 0)
        assert "session.created" in await anext(stream)
        await stream.aclose()

    async def model(_):
        return RunResult("模拟模型完成")

    worker = Worker({(context.graph_key, context.graph_version): model}, sessions=factory)
    await worker.execute(context)
    async with factory() as db:
        result = await queries.snapshot(db, sid, "test-user")
        assert result["recent_run_results"][0]["status"] == "SUCCEEDED"
        assert len(result["messages"]) == 2
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_upload_decode_idempotency_and_ownership(client, db_session):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    key = str(uuid4())
    first = await upload(client, sid, key)
    assert (await upload(client, sid, key))["id"] == first["id"]
    assert first["width_px"] == 4 and first["height_px"] == 3
    corrupt = await client.post(
        f"/api/agent/v2/sessions/{sid}/attachments",
        data={"client_upload_id": str(uuid4())},
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert corrupt.status_code == 422
    foreign = (await create(client, "ORDER_INTAKE"))["id"]
    rejected = await client.post(
        f"/api/agent/v2/sessions/{foreign}/messages", json=body(content="", attachment_ids=[first["id"]])
    )
    assert rejected.status_code == 404
    metadata = await db_session.get(ChatAttachment, first["id"])
    assert metadata.status == "STAGED"
    assert "storage_key" not in first and "sha256" not in first
    image = await client.get(f"/api/agent/v2/attachments/{first['id']}/content")
    assert image.status_code == 200 and image.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_archive_restore_and_feature_gate(client, monkeypatch):
    sid = (await create(client))["id"]
    archived = await client.post(
        f"/api/agent/v2/sessions/{sid}/archive", headers={"Idempotency-Key": str(uuid4())}
    )
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
    assert (await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=body(2))).status_code == 409
    restored = await client.post(
        f"/api/agent/v2/sessions/{sid}/restore", headers={"Idempotency-Key": str(uuid4())}
    )
    assert restored.json()["status"] == "ACTIVE"
    monkeypatch.setattr(settings, "AGENT_V2_ENABLED", False)
    assert (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).status_code == 503


@pytest.mark.asyncio
async def test_queue_timeout_and_cross_session_constraint(client, db_session):
    sid = (await create(client))["id"]
    accepted = (await client.post(f"/api/agent/v2/sessions/{sid}/messages", json=body())).json()
    run = await db_session.get(AgentRun, accepted["run_id"])
    run.queued_at = datetime.now(UTC) - timedelta(seconds=121)
    await db_session.commit()
    assert await claim(db_session, "late") is None
    assert run.status == "FAILED" and run.error_code == "QUEUE_TIMEOUT"
    other = (await create(client))["id"]
    other_result = (await client.post(f"/api/agent/v2/sessions/{other}/messages", json=body())).json()
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            run.output_message_id = other_result["message_id"]
            await db_session.flush()
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_tool_receipts_rollback_deduplicate_and_fence(independent_sessions):
    from app.models import AgentAuditLog, AgentToolCall
    from app.services.agent_tool_service import perform_tool

    factory = independent_sessions
    async with factory() as db:
        sid = (
            await service.create_session(
                db,
                "test-user",
                str(uuid4()),
                CreateSession(agent_type="SCHEDULING", title="concurrency-test"),
            )
        )["session"]["id"]
        await service.accept_message(db, sid, "test-user", SendMessage(**body()))
        context = await claim(db, "worker")
    writes = 0

    async def write(db):
        nonlocal writes
        writes += 1
        session = await db.get(ChatSession, sid)
        session.state = {"hint": "saved"}
        return {"saved": True}

    args = dict(
        call_key="call-1", tool_name="prepare", args={}, allowed_tools=frozenset({"prepare"}), operation=write
    )
    assert await perform_tool(factory, context, **args) == {"saved": True}
    assert await perform_tool(factory, context, **args) == {"saved": True}
    assert writes == 1

    async def broken(db):
        session = await db.get(ChatSession, sid)
        session.state = {"hint": "must roll back"}
        await db.flush()
        raise ValueError("upstream secret must not be persisted")

    with pytest.raises(ValueError):
        await perform_tool(factory, context, **{**args, "call_key": "call-2", "operation": broken})
    async with factory() as db:
        assert (await db.get(ChatSession, sid)).state == {"hint": "saved"}
        call = await db.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == context.run_id, AgentToolCall.call_key == "call-2"
            )
        )
        assert call.error_code == "TOOL_FAILED" and call.result is None
        run = await db.get(AgentRun, context.run_id)
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        await expire_runs(db)
    with pytest.raises(LeaseLost):
        await perform_tool(factory, context, **{**args, "call_key": "call-3"})
    assert writes == 1
    async with factory() as db:
        audit = await db.scalar(select(AgentAuditLog).where(AgentAuditLog.run_id == context.run_id))
        assert audit.kind == "RUN_FINISHED" and audit.prompt is None and audit.total_tokens is None
        assert audit.result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_independent_sessions_run_concurrently_and_model_failure_is_safe(independent_sessions):
    factory = independent_sessions
    contexts = []
    for _ in range(2):
        async with factory() as db:
            sid = (
                await service.create_session(
                    db,
                    "test-user",
                    str(uuid4()),
                    CreateSession(agent_type="SCHEDULING", title="concurrency-test"),
                )
            )["session"]["id"]
            await service.accept_message(db, sid, "test-user", SendMessage(**body()))
            contexts.append(await claim(db, "worker"))
    barrier = asyncio.Barrier(2)

    async def model(context):
        await asyncio.wait_for(barrier.wait(), 3)
        if context.run_id == contexts[0].run_id:
            raise RuntimeError("SECRET_PROVIDER_KEY")
        return RunResult("正常完成")

    worker = Worker({(contexts[0].graph_key, contexts[0].graph_version): model}, sessions=factory)
    await asyncio.gather(*(worker.execute(context) for context in contexts))
    async with factory() as db:
        failed = await db.get(AgentRun, contexts[0].run_id)
        success = await db.get(AgentRun, contexts[1].run_id)
        assert failed.status == "FAILED" and failed.error_code == "EXECUTION_FAILED"
        assert "SECRET" not in failed.error_message
        assert success.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_expired_upload_and_orphan_cleanup(client, db_session):
    import os
    import time
    from pathlib import Path

    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    attachment = await db_session.get(ChatAttachment, image["id"])
    file = Path(settings.CHAT_ATTACHMENT_DIR) / attachment.storage_key
    attachment.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await gc.sweep_staged(db_session) == 1
    assert await gc.collect_once(db_session)
    assert not file.exists()
    orphan = Path(settings.CHAT_ATTACHMENT_DIR) / (uuid4().hex + ".png")
    orphan.write_bytes(b"orphan")
    os.utime(orphan, (time.time() - 86500, time.time() - 86500))
    assert await gc.sweep_orphans(db_session) == 1
    assert await gc.sweep_orphans(db_session) == 0
    assert await gc.collect_once(db_session)
    assert not orphan.exists()


@pytest.mark.asyncio
async def test_session_paging_history_and_legacy_cutover_guard(client, db_session):
    first = await create(client, "ORDER_INTAKE")
    second = await create(client, "SCHEDULING")
    page = (await client.get("/api/agent/v2/sessions?limit=1")).json()
    assert page["items"][0]["id"] == second["id"] and page["next_cursor"]
    rest = (await client.get("/api/agent/v2/sessions", params={"cursor": page["next_cursor"]})).json()
    assert rest["items"][0]["id"] == first["id"]
    filtered = (await client.get("/api/agent/v2/sessions?agent_type=ORDER_INTAKE")).json()
    assert [row["id"] for row in filtered["items"]] == [first["id"]]
    assert (await client.get("/api/agent/v2/sessions?cursor=invalid")).status_code == 422
    accepted = (await client.post(f"/api/agent/v2/sessions/{second['id']}/messages", json=body())).json()
    context = await claim(db_session, "worker")
    await finalize(db_session, context, RunResult("已完成"))
    snapshot = (await client.get(f"/api/agent/v2/sessions/{second['id']}/snapshot")).json()
    last_seq = snapshot["messages"][-1]["event_seq"]
    older = (await client.get(f"/api/agent/v2/sessions/{second['id']}/messages?before={last_seq}")).json()
    assert [m["id"] for m in older["items"]] == [accepted["message_id"]]
    assert (await client.post("/api/agent/sessions", json={})).status_code == 404
    assert (await client.post("/api/schedule-plans/old-plan/apply", json={})).status_code == 404


@pytest.mark.asyncio
async def test_oversized_chunked_request_rejected_before_multipart(client):
    async def chunks():
        for _ in range(7):
            yield b"x" * (1024 * 1024)

    response = await client.post("/api/agent/v2/sessions/unknown/attachments", content=chunks())
    assert response.status_code == 413 and response.json()["error"]["code"] == "ATTACHMENT_LIMIT"


@pytest.mark.asyncio
async def test_concurrent_order_confirmation_and_session_gc_preserve_business_order(independent_sessions):
    from sqlalchemy import delete

    from app.models import AgentAuditLog, Customer, Order, Product, ProductCategory
    from app.services import agent_attachment_service as attachments
    from app.services import order_intake_item_service as intake
    from tests.test_order_intake_v2 import seed_fields

    factory = independent_sessions
    async with factory() as db:
        fields = await seed_fields(db)
        category_id = (await db.get(Product, fields["product_id"])).category_id
        sid = (
            await service.create_session(
                db,
                "test-user",
                str(uuid4()),
                CreateSession(agent_type="ORDER_INTAKE", title="concurrency-test"),
            )
        )["session"]["id"]
        output = io.BytesIO()
        Image.new("RGB", (4, 3)).save(output, format="PNG")
        attachment = await attachments.upload(db, sid, "test-user", str(uuid4()), output.getvalue())
        await service.accept_message(
            db, sid, "test-user", SendMessage(**body(attachment_ids=[attachment["id"]]))
        )
        context = await claim(db, "worker")
        await finalize(db, context, RunResult("请核对草稿"))
        session, item = await intake.require_item(db, context.work_item_id, "test-user")
        patched = await intake.patch_draft(db, session, item, item.revision, fields)
        await db.commit()
        iid, revision = item.id, patched["revision"]

    gate = asyncio.Barrier(2)

    async def confirm():
        async with factory() as db:
            await gate.wait()
            return await intake.item_command(
                db, iid, "test-user", str(uuid4()), "CONFIRM_ORDER", {"expected_revision": revision}
            )

    try:
        results = await asyncio.gather(confirm(), confirm())
        assert results[0]["order"]["id"] == results[1]["order"]["id"]
        assert sum(result["returned_existing"] for result in results) == 1
        oid = results[0]["order"]["id"]
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count()).select_from(Order).where(Order.product_id == fields["product_id"])
                )
                == 1
            )
            await service.change_status(db, sid, "test-user", str(uuid4()), "DELETE_SESSION")
            assert await gc.collect_once(db)
            assert await gc.finish_deletions(db) == 1
            assert await db.get(ChatSession, sid) is None
            assert await db.get(Order, oid) is not None
            audits = (await db.scalars(select(AgentAuditLog).where(AgentAuditLog.object_id == oid))).all()
            assert len(audits) == 1 and audits[0].session_id is None and audits[0].prompt is None
    finally:
        async with factory() as db:
            # Remove only this test's committed business fixture after its Session has been cleared.
            order_ids = (
                await db.scalars(select(Order.id).where(Order.product_id == fields["product_id"]))
            ).all()
            await db.execute(
                delete(AgentAuditLog).where(AgentAuditLog.object_id.in_([context.run_id, *order_ids]))
            )
            await db.execute(delete(ChatSession).where(ChatSession.id == sid))
            await db.execute(delete(Order).where(Order.product_id == fields["product_id"]))
            await db.execute(delete(Product).where(Product.id == fields["product_id"]))
            await db.execute(delete(Customer).where(Customer.id == fields["customer_id"]))
            await db.execute(delete(ProductCategory).where(ProductCategory.id == category_id))
            await db.commit()
