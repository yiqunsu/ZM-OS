import pytest
from fastapi import HTTPException

from app.agent import model_transport


@pytest.mark.parametrize(
    "host,model,mode,thinking",
    [
        ("https://api.deepseek.com", "deepseek-v4-flash-vision-exp", "disabled", {"type": "disabled"}),
        ("https://api.deepseek.com", "deepseek-flash", "disabled", {"type": "disabled"}),
        ("https://api.deepseek.com", "deepseek-flash", "enabled", {"type": "enabled"}),
        ("https://api.deepseek.com", "deepseek-flash", "provider_default", None),
        ("https://other.example/v1", "deepseek-v4-flash-vision-exp", "disabled", None),
    ],
)
async def test_vision_request_options_are_scoped_and_truncated_results_rejected(
    monkeypatch, host, model, mode, thinking
):
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_VISION_THINKING", mode)
    monkeypatch.setattr(settings, "LLM_VISION_MAX_TOKENS", 12345)
    monkeypatch.setattr(settings, "LLM_BASE_URL", host)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-only-key")
    original = httpx.AsyncClient

    def reply(request):
        import json

        payload = json.loads(request.content)
        assert payload.get("thinking") == thinking
        assert payload["max_tokens"] == 12345
        # A syntactically complete JSON can still be a truncated subset of orders.
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"orders": [{}]}'}}]}
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reply), **kw)
    )
    with pytest.raises(HTTPException, match="截断"):
        await model_transport.call_vision_model([], model)


@pytest.mark.parametrize(
    "failure,code",
    [
        ("connection", "CONNECTION_ERROR"),
        ("timeout", "TIMEOUT"),
        ("http", "HTTP_ERROR"),
        ("json", "JSON_INVALID"),
        ("shape", "RESPONSE_INVALID"),
        ("null_choice", "RESPONSE_INVALID"),
        ("null_message", "RESPONSE_INVALID"),
    ],
)
async def test_vision_failures_have_safe_diagnostic_codes(monkeypatch, failure, code):
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_KEY", "test-only-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://example.invalid/v1")
    original = httpx.AsyncClient

    def reply(request):
        if failure == "connection":
            raise httpx.ConnectError("private upstream detail", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream detail", request=request)
        if failure == "http":
            return httpx.Response(503, text="private upstream detail")
        if failure == "null_choice":
            return httpx.Response(200, json={"choices": [None]})
        if failure == "null_message":
            return httpx.Response(200, json={"choices": [{"message": None}]})
        if failure == "shape":
            return httpx.Response(200, json={"private": "upstream detail"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "private invalid text"}}]})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reply), **kw)
    )
    with pytest.raises(model_transport.VisionError) as caught:
        await model_transport.call_vision_model([], "model")
    assert caught.value.code == code
    assert "private" not in caught.value.detail and "test-only-key" not in caught.value.detail
