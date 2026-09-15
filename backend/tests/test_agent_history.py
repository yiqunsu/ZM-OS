"""Retired routes must stay inaccessible even with pre-migration legacy rows."""
import pytest

from app.core.config import settings
from app.models import ChatSession


@pytest.mark.parametrize("enabled", [True, False])
async def test_old_routes_removed_without_fallback(client, monkeypatch, enabled):
    monkeypatch.setattr(settings, "AGENT_V2_ENABLED", enabled)
    for method, path in (
        ("get", "/api/agent/sessions"),
        ("post", "/api/agent/sessions"),
        ("post", "/api/agent/chat"),
        ("post", "/api/agent/chat/confirm"),
        ("get", "/api/schedule-plans/old"),
        ("get", "/api/agent/v2/history/sessions"),
        ("get", "/api/agent/v2/history/sessions/old/messages"),
        ("get", "/api/agent/v2/history/attachments/old/content"),
    ):
        assert (await getattr(client, method)(path)).status_code == 404


async def test_new_api_cannot_read_legacy_session(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_V2_ENABLED", True)
    db_session.add(ChatSession(id="retired-session", title="已退役", user_id="test-user"))
    await db_session.commit()
    assert (await client.get("/api/agent/v2/sessions/retired-session/snapshot")).status_code == 404
    result = (await client.get("/api/agent/v2/sessions")).json()
    assert all(s["id"] != "retired-session" for s in result["items"])
