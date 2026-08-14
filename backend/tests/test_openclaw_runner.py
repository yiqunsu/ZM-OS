from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.agent.runner as runner
from app.agent.runtime import RuntimeEvent
from app.models import AgentAuditLog, ChatMessage, ChatSession

TEST_DB_URL = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos_test"


@pytest_asyncio.fixture
async def runner_db(monkeypatch, tmp_path):
    engine = create_async_engine(TEST_DB_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "async_session", maker)
    monkeypatch.setattr(runner.settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))

    async with maker() as db:
        session = ChatSession(title="OpenClaw runner test", user_id="test-user")
        db.add(session)
        await db.commit()
        session_id = session.id

    yield maker, session_id

    async with maker() as db:
        await db.execute(delete(AgentAuditLog).where(AgentAuditLog.session_id == session_id))
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
        await db.commit()
    await engine.dispose()


async def test_openclaw_runner_preserves_sse_history_and_audit(monkeypatch, runner_db):
    maker, session_id = runner_db
    captured: dict[str, str] = {}

    async def fake_stream_text(request_session_id: str, user_id: str, text: str):
        captured.update(session_id=request_session_id, user_id=user_id, text=text)
        yield RuntimeEvent(type="delta", content="你")
        yield RuntimeEvent(type="delta", content="好")
        yield RuntimeEvent(
            type="completed",
            usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
        )

    monkeypatch.setattr(runner.openclaw_runtime, "stream_text", fake_stream_text)

    events = [
        event
        async for event in runner._stream_openclaw_turn(
            session_id,
            "你好",
            "test-user",
            "test@filmos.local",
        )
    ]

    assert captured == {"session_id": session_id, "user_id": "test-user", "text": "你好"}
    assert [event["type"] for event in events] == ["delta", "delta", "text_done"]
    assert "message_id" in events[-1]
    assert "user_message_id" in events[-1]

    async with maker() as db:
        messages = list(
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                )
            )
            .scalars()
            .all()
        )
        audit = (
            await db.execute(select(AgentAuditLog).where(AgentAuditLog.session_id == session_id))
        ).scalar_one()

    assert [(message.role, message.content) for message in messages] == [
        ("user", "你好"),
        ("assistant", "你好"),
    ]
    assert audit.skill == "openclaw-text"
    assert audit.total_tokens == 6


async def test_openclaw_error_identifies_persisted_user_message(monkeypatch, runner_db):
    maker, session_id = runner_db

    async def fake_stream_text(_session_id: str, _user_id: str, _text: str):
        raise RuntimeError("gateway unavailable")
        yield

    monkeypatch.setattr(runner.openclaw_runtime, "stream_text", fake_stream_text)

    events = [
        event
        async for event in runner._stream_openclaw_turn(
            session_id,
            "你好",
            "test-user",
            "test@filmos.local",
        )
    ]

    async with maker() as db:
        user_message = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "user",
                )
            )
        ).scalar_one()

    assert events == [
        {
            "type": "error",
            "error": "AI 助手暂时不可用，请稍后重试",
            "user_message_id": user_message.id,
        }
    ]


async def test_order_intake_workspace_routes_followup_turns(monkeypatch, runner_db):
    maker, session_id = runner_db
    extracted_texts: list[str] = []

    async def fake_extract(_db, text, _image_data_url=None):
        extracted_texts.append(text)
        return {"quantity": 500} if "500" in text else {}

    monkeypatch.setattr(runner.order_intake_service, "extract_order_draft", fake_extract)

    first_events = [
        event
        async for event in runner.stream_turn(
            session_id, "帮我录单", "test-user", "test@filmos.local"
        )
    ]
    second_events = [
        event
        async for event in runner.stream_turn(
            session_id, "华兴，500kg", "test-user", "test@filmos.local"
        )
    ]

    assert extracted_texts == ["帮我录单", "华兴，500kg"]
    assert any(event["type"] == "panel" for event in first_events)
    assert any(
        event["type"] == "form_update" and event["fields"] == {"quantity": 500}
        for event in second_events
    )
    async with maker() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_workspace == "order_form"
        assert session.workspace_state == {"order_draft": {"quantity": 500}}


async def test_order_intake_error_identifies_persisted_user_message(monkeypatch, runner_db):
    maker, session_id = runner_db

    async def fake_extract(_db, _text, _image_data_url=None):
        raise RuntimeError("vision provider unavailable")

    monkeypatch.setattr(runner.order_intake_service, "extract_order_draft", fake_extract)

    events = [
        event
        async for event in runner.stream_turn(
            session_id,
            "",
            "test-user",
            "test@filmos.local",
            "data:image/png;base64,iVBORw0KGgp0ZXN0",
        )
    ]

    assert [event["type"] for event in events] == [
        "user_message_committed",
        "panel",
        "error",
    ]
    assert events[-1]["error"] == "订单信息识别失败，请重试"
    async with maker() as db:
        user_message = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "user",
                )
            )
        ).scalar_one()
    assert user_message.content == "[图片订单]"
    assert events[-1]["user_message_id"] == user_message.id
    assert events[0]["user_message_id"] == user_message.id
    assert len(events[0]["attachments"]) == 1


async def test_invalid_image_fails_before_user_message_commit(runner_db):
    maker, session_id = runner_db

    events = [
        event
        async for event in runner.stream_turn(
            session_id,
            "",
            "test-user",
            "test@filmos.local",
            "data:image/png;base64,aW1hZ2U=",
        )
    ]

    assert events == [{"type": "error", "error": "PNG 图片内容无效"}]
    async with maker() as db:
        messages = list(
            (
                await db.execute(
                    select(ChatMessage).where(ChatMessage.session_id == session_id)
                )
            ).scalars()
        )
    assert messages == []


async def test_order_submit_without_active_form_does_not_create_pending_action(runner_db):
    maker, session_id = runner_db

    events = [
        event
        async for event in runner.stream_turn(
            session_id, "确认下发订单", "test-user", "test@filmos.local"
        )
    ]

    assert [event["type"] for event in events] == [
        "user_message_committed",
        "delta",
        "text_done",
    ]
    assert "没有打开的订单表单" in events[1]["content"]
    async with maker() as db:
        pending = list(
            (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.session_id == session_id,
                        ChatMessage.is_pending.is_(True),
                    )
                )
            ).scalars()
        )
    assert pending == []


async def test_schedule_plan_sets_active_workspace_after_generation(monkeypatch, runner_db):
    maker, session_id = runner_db

    async def fake_create_schedule_plan(_db, request_session_id, user_id):
        assert request_session_id == session_id
        assert user_id == "test-user"
        return SimpleNamespace(
            id="plan-test",
            status=SimpleNamespace(value="DRAFT"),
            tasks=[],
            unassigned=[],
            created_at=SimpleNamespace(isoformat=lambda: "2026-07-30T00:00:00+00:00"),
        )

    monkeypatch.setattr(
        runner.schedule_service,
        "create_schedule_plan",
        fake_create_schedule_plan,
    )

    events = [
        event
        async for event in runner.stream_turn(
            session_id, "帮我排产", "test-user", "test@filmos.local"
        )
    ]

    assert any(event["type"] == "schedule_plan" for event in events)
    async with maker() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_workspace == "schedule_plan"
