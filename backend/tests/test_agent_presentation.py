import pytest
from pydantic import ValidationError

from app.models import ChatMessage
from app.schemas.agent_presentation import AgentPresentation, board_presentation, schedule_presentation
from tests.test_scheduling import _setup_schedulable


def test_schedule_card_uses_tool_counts_and_reasons():
    card = schedule_presentation({
        "tasks": [
            {"machine_name": "A", "order_ids": ["1", "2"]},
            {"machine_name": "A", "order_ids": ["3"]},
        ],
        "unassigned": [{"order_no": "O4", "reason": "幅宽不匹配"}],
    })
    assert [m.value for m in card.metrics] == [2, 3, 1]
    assert len(card.rows) == 1
    assert card.rows[0].detail == "2 个新任务"
    assert card.warnings == ["O4：幅宽不匹配"]
    assert "快照" in card.next_step


def test_empty_board_and_invalid_contract():
    card = board_presentation({"machines": [], "pending_orders": []})
    assert [m.value for m in card.metrics] == [0, 0, 0]
    with pytest.raises(ValidationError):
        AgentPresentation.model_validate({**card.model_dump(), "version": 2})


async def test_card_survives_history_and_old_messages_remain_compatible(client, db_session):
    session, _, _ = await _setup_schedulable(db_session)
    session.agent_type = "SCHEDULING"
    card = board_presentation({"machines": [], "pending_orders": []}).model_dump()
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
