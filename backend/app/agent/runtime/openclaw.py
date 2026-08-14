"""Private OpenClaw Gateway client for the text-only first milestone."""

import hashlib
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.agent.runtime.base import AgentRuntimeError, RuntimeEvent
from app.core.config import settings
from app.core.logging import logger


def _session_user(user_id: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
    return f"filmos-{digest}"


def _usage(payload: dict[str, Any]) -> dict[str, int]:
    response = payload.get("response")
    raw = response.get("usage") if isinstance(response, dict) else payload.get("usage")
    if not isinstance(raw, dict):
        return {}

    input_tokens = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
    output_tokens = int(raw.get("output_tokens") or raw.get("completion_tokens") or 0)
    total_tokens = int(raw.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


async def _decode_event(event_name: str | None, data_lines: list[str]) -> AsyncGenerator[RuntimeEvent, None]:
    raw_data = "\n".join(data_lines)
    if not raw_data or raw_data == "[DONE]":
        return
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError as err:
        raise AgentRuntimeError() from err
    if not isinstance(payload, dict):
        raise AgentRuntimeError()

    event_type = event_name or payload.get("type")
    if event_type == "response.output_text.delta":
        delta = payload.get("delta")
        if isinstance(delta, str) and delta:
            yield RuntimeEvent(type="delta", content=delta)
    elif event_type == "response.completed":
        yield RuntimeEvent(type="completed", usage=_usage(payload))
    elif event_type == "response.failed":
        raise AgentRuntimeError()


async def stream_text(
    session_id: str,
    user_id: str,
    text: str,
) -> AsyncGenerator[RuntimeEvent, None]:
    if not settings.OPENCLAW_GATEWAY_TOKEN:
        logger.error("openclaw_configuration_missing", field="OPENCLAW_GATEWAY_TOKEN")
        raise AgentRuntimeError("AI 助手尚未配置")

    url = f"{settings.OPENCLAW_BASE_URL.rstrip('/')}/v1/responses"
    headers = {
        "Authorization": f"Bearer {settings.OPENCLAW_GATEWAY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-openclaw-agent-id": settings.OPENCLAW_AGENT_ID,
    }
    body = {
        "model": f"openclaw/{settings.OPENCLAW_AGENT_ID}",
        "input": text,
        "user": _session_user(user_id, session_id),
        "stream": True,
    }
    timeout = httpx.Timeout(
        settings.OPENCLAW_REQUEST_TIMEOUT_SECONDS,
        connect=min(settings.OPENCLAW_REQUEST_TIMEOUT_SECONDS, 10.0),
    )
    completed = False

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    logger.error(
                        "openclaw_request_failed",
                        status_code=response.status_code,
                        session_id=session_id,
                    )
                    raise AgentRuntimeError()

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    logger.error(
                        "openclaw_protocol_error",
                        reason="unexpected_content_type",
                        session_id=session_id,
                    )
                    raise AgentRuntimeError()

                event_name: str | None = None
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if not line:
                        async for event in _decode_event(event_name, data_lines):
                            if event.type == "completed":
                                completed = True
                            yield event
                        event_name = None
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    field, separator, value = line.partition(":")
                    if not separator:
                        continue
                    value = value.lstrip(" ")
                    if field == "event":
                        event_name = value
                    elif field == "data":
                        if value == "[DONE]":
                            break
                        data_lines.append(value)

                if data_lines:
                    async for event in _decode_event(event_name, data_lines):
                        if event.type == "completed":
                            completed = True
                        yield event
                if not completed:
                    logger.error(
                        "openclaw_protocol_error",
                        reason="stream_ended_before_completion",
                        session_id=session_id,
                    )
                    raise AgentRuntimeError()
    except AgentRuntimeError:
        raise
    except (httpx.HTTPError, TimeoutError) as err:
        logger.error(
            "openclaw_transport_error",
            error_type=type(err).__name__,
            session_id=session_id,
        )
        raise AgentRuntimeError() from err
