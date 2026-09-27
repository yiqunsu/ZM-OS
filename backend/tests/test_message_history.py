"""Retired presentation payloads remain readable alongside plain-text messages."""

from app.models import ChatMessage
from tests.test_scheduling import _setup_schedulable


async def test_card_survives_history_and_old_messages_remain_compatible(client, db_session):
    session, _, _ = await _setup_schedulable(db_session)
    session.agent_type = "SCHEDULING"
    # Retained historical JSON must remain readable without its retired generator.
    card = {
        "version": 1,
        "kind": "board",
        "title": "历史概况",
        "metrics": [],
        "rows": [],
        "warnings": [],
        "next_step": "历史快照",
    }
    db_session.add(ChatMessage(session_id=session.id, role="assistant", content="概况", presentation=card))
    db_session.add(ChatMessage(session_id=session.id, role="assistant", content="旧消息"))
    await db_session.commit()
    response = await client.get(f"/api/agent/v2/sessions/{session.id}/snapshot")
    assert response.status_code == 200, response.text
    assert any(message["presentation"] == card for message in response.json()["messages"])
    assert any(
        message["content"] == "旧消息" and message["presentation"] is None
        for message in response.json()["messages"]
    )
