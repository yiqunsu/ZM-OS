"""Model response decoding and bounded multimodal HTTP; no business matching or writes."""

import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from app.core.config import settings


class VisionError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(status_code, message)
        self.code = code


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    return ""


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise HTTPException(502, "订单信息识别结果无效，请重试") from err
    if not isinstance(parsed, dict):
        raise HTTPException(502, "订单信息识别结果无效，请重试")
    return parsed


async def call_vision_model(
    messages: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    if not settings.LLM_API_KEY:
        raise VisionError("NOT_CONFIGURED", "订单识别模型尚未配置", 503)
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.LLM_VISION_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    # Provider extension is explicit and independent of model aliases.
    if (
        urlsplit(settings.LLM_BASE_URL).hostname == "api.deepseek.com"
        and settings.LLM_VISION_THINKING != "provider_default"
    ):
        payload["thinking"] = {"type": settings.LLM_VISION_THINKING}
    timeout = httpx.Timeout(settings.LLM_REQUEST_TIMEOUT_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as err:
        raise VisionError("TIMEOUT", "订单识别超时，请重试") from err
    except httpx.HTTPStatusError as err:
        raise VisionError("HTTP_ERROR", "订单识别服务暂时不可用，请稍后重试") from err
    except httpx.RequestError as err:
        raise VisionError("CONNECTION_ERROR", "订单识别连接失败，请重试") from err
    except ValueError as err:
        raise VisionError("RESPONSE_INVALID", "订单识别服务返回异常，请重试") from err
    try:
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":
            raise VisionError("OUTPUT_TRUNCATED", "截图识别结果被截断，请重试或拆分截图")
        if choice["message"].get("tool_calls"):
            raise VisionError("RESPONSE_INVALID", "订单识别返回了不支持的工具调用")
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, AttributeError) as err:
        raise VisionError("RESPONSE_INVALID", "订单识别服务返回异常，请重试") from err
    try:
        return parse_json_object(content_text(content))
    except HTTPException as err:
        raise VisionError("JSON_INVALID", "订单识别JSON格式无效，请重试") from err
