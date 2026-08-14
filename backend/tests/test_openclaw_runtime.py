import json

import pytest

from app.agent.runtime import AgentRuntimeError, openclaw
from app.core.config import settings


class _FakeResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code
        self.headers = {"content-type": "text/event-stream"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    def __init__(self, response: _FakeResponse, captured: dict):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method, url, *, headers, json):
        self._captured.update(method=method, url=url, headers=headers, body=json)
        return self._response


async def test_openclaw_stream_translates_responses_sse(monkeypatch):
    completed = {
        "type": "response.completed",
        "response": {"usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11}},
    }
    response = _FakeResponse(
        [
            "event: response.output_text.delta",
            'data: {"delta":"你"}',
            "",
            "event: response.output_text.delta",
            'data: {"delta":"好"}',
            "",
            "event: response.completed",
            f"data: {json.dumps(completed)}",
            "",
            "data: [DONE]",
            "",
        ]
    )
    captured: dict = {}
    monkeypatch.setattr(settings, "OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    monkeypatch.setattr(settings, "OPENCLAW_BASE_URL", "http://openclaw:18789")
    monkeypatch.setattr(settings, "OPENCLAW_AGENT_ID", "filmos-web")
    monkeypatch.setattr(
        openclaw.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(response, captured),
    )

    events = [event async for event in openclaw.stream_text("session-1", "user-1", "你好")]

    assert [event.type for event in events] == ["delta", "delta", "completed"]
    assert "".join(event.content for event in events) == "你好"
    assert events[-1].usage == {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11}
    assert captured["url"] == "http://openclaw:18789/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer test-gateway-token"
    assert captured["body"]["model"] == "openclaw/filmos-web"
    assert captured["body"]["input"] == "你好"
    assert captured["body"]["user"].startswith("filmos-")
    assert captured["body"]["user"] != "user-1"


async def test_openclaw_session_identity_isolated_by_user_and_session():
    assert openclaw._session_user("user-a", "session-a") == openclaw._session_user("user-a", "session-a")
    assert openclaw._session_user("user-a", "session-a") != openclaw._session_user("user-b", "session-a")
    assert openclaw._session_user("user-a", "session-a") != openclaw._session_user("user-a", "session-b")


async def test_openclaw_http_failure_returns_safe_runtime_error(monkeypatch):
    response = _FakeResponse([], status_code=503)
    monkeypatch.setattr(settings, "OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    monkeypatch.setattr(
        openclaw.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(response, {}),
    )

    with pytest.raises(AgentRuntimeError, match="AI 助手暂时不可用"):
        _ = [event async for event in openclaw.stream_text("session-1", "user-1", "hi")]


async def test_openclaw_requires_gateway_token(monkeypatch):
    monkeypatch.setattr(settings, "OPENCLAW_GATEWAY_TOKEN", "")

    with pytest.raises(AgentRuntimeError, match="AI 助手尚未配置"):
        _ = [event async for event in openclaw.stream_text("session-1", "user-1", "hi")]


async def test_openclaw_rejects_incomplete_stream(monkeypatch):
    response = _FakeResponse(
        [
            "event: response.output_text.delta",
            'data: {"delta":"partial"}',
            "",
        ]
    )
    monkeypatch.setattr(settings, "OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    monkeypatch.setattr(
        openclaw.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(response, {}),
    )

    with pytest.raises(AgentRuntimeError, match="AI 助手暂时不可用"):
        _ = [event async for event in openclaw.stream_text("session-1", "user-1", "hi")]
