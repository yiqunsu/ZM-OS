"""Controlled multimodal extraction for the collaborative order form."""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Customer, Formula, Product

_DATA_URL_RE = re.compile(r"^data:(image/(?:jpeg|png));base64,([A-Za-z0-9+/=\r\n]+)$")
_IMAGE_DATA_URL_PREFIXES = ("data:image/jpeg;base64,", "data:image/png;base64,")
_ALLOWED_FIELDS = {
    "customer_id",
    "product_id",
    "spec_params",
    "quantity",
    "unit",
    "formula_id",
    "extra_notes",
}


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    data_url: str
    mime_type: str
    content: bytes


def decode_image_data_url(data_url: str) -> ValidatedImage:
    prefix = next(
        (candidate for candidate in _IMAGE_DATA_URL_PREFIXES if data_url.startswith(candidate)),
        None,
    )
    if prefix is None:
        raise HTTPException(400, "仅支持 JPG 或 PNG 图片")
    encoded_length = len(data_url) - len(prefix)
    max_encoded_length = 4 * ((settings.AGENT_IMAGE_MAX_BYTES + 2) // 3)
    if encoded_length > max_encoded_length:
        max_mb = settings.AGENT_IMAGE_MAX_BYTES // (1024 * 1024)
        raise HTTPException(413, f"图片不能超过 {max_mb}MB")
    match = _DATA_URL_RE.fullmatch(data_url)
    if match is None:
        raise HTTPException(400, "仅支持 JPG 或 PNG 图片")
    mime_type, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as err:
        raise HTTPException(400, "图片内容无效") from err
    if not raw:
        raise HTTPException(400, "图片内容为空")
    if len(raw) > settings.AGENT_IMAGE_MAX_BYTES:
        max_mb = settings.AGENT_IMAGE_MAX_BYTES // (1024 * 1024)
        raise HTTPException(413, f"图片不能超过 {max_mb}MB")
    if mime_type == "image/jpeg" and not raw.startswith(b"\xff\xd8\xff"):
        raise HTTPException(400, "JPG 图片内容无效")
    if mime_type == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(400, "PNG 图片内容无效")
    return ValidatedImage(data_url=data_url, mime_type=mime_type, content=raw)


def validate_image_data_url(data_url: str) -> str:
    return decode_image_data_url(data_url).data_url


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "") for item in content if isinstance(item, dict)
        )
    return ""


def _parse_json_object(text: str) -> dict[str, Any]:
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


async def _call_model(
    messages: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    if not settings.LLM_API_KEY:
        raise HTTPException(503, "订单识别模型尚未配置")
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    timeout = httpx.Timeout(settings.LLM_REQUEST_TIMEOUT_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as err:
        raise HTTPException(502, "订单识别服务暂时不可用，请稍后重试") from err
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as err:
        raise HTTPException(502, "订单识别服务返回异常，请重试") from err
    return _parse_json_object(_content_text(content))


def _candidate_prompt(
    customers: list[Customer], products: list[Product], formulas: list[Formula]
) -> str:
    candidates = {
        "customers": [
            {"id": customer.id, "company": customer.company, "contact": customer.contact}
            for customer in customers
        ],
        "products": [
            {"id": product.id, "name": product.name, "category": product.category.name}
            for product in products
        ],
        "formulas": [
            {"id": formula.id, "name": formula.name, "product_id": formula.product_id}
            for formula in formulas
        ],
    }
    return (
        "你是薄膜工厂订单字段提取器。只返回 JSON 对象，不要解释。"
        "允许字段：customer_id, customer_name, product_id, product_name, spec_params, "
        "quantity, unit, formula_id, formula_name, extra_notes。"
        "未知字段不要返回，不得猜测 ID；规格中的厚度规范为 μm，宽度规范为 mm；"
        "单位只允许 kg 或 t。候选基础数据如下：\n"
        + json.dumps(candidates, ensure_ascii=False)
    )


def _match_named_id(value: Any, name: Any, rows: list[Any], label_attr: str) -> str | None:
    valid_ids = {row.id for row in rows}
    if isinstance(value, str) and value in valid_ids:
        return value
    if not isinstance(name, str) or not name.strip():
        return None
    keyword = name.strip().casefold()
    exact = [row.id for row in rows if str(getattr(row, label_attr)).strip().casefold() == keyword]
    if len(exact) == 1:
        return exact[0]
    partial = [
        row.id
        for row in rows
        if keyword in str(getattr(row, label_attr)).casefold()
        or str(getattr(row, label_attr)).casefold() in keyword
    ]
    return partial[0] if len(partial) == 1 else None


def _normalize_draft(
    raw: dict[str, Any],
    customers: list[Customer],
    products: list[Product],
    formulas: list[Formula],
) -> dict[str, Any]:
    draft: dict[str, Any] = {}
    customer_id = _match_named_id(raw.get("customer_id"), raw.get("customer_name"), customers, "company")
    product_id = _match_named_id(raw.get("product_id"), raw.get("product_name"), products, "name")
    if customer_id:
        draft["customer_id"] = customer_id
    if product_id:
        draft["product_id"] = product_id

    specs = raw.get("spec_params")
    if isinstance(specs, dict):
        normalized_specs = {
            str(key).strip(): str(value).strip()
            for key, value in specs.items()
            if str(key).strip() and value is not None and str(value).strip()
        }
        if normalized_specs:
            draft["spec_params"] = normalized_specs

    quantity = raw.get("quantity")
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity > 0:
        draft["quantity"] = float(quantity)
    elif isinstance(quantity, str):
        try:
            parsed_quantity = float(quantity.strip())
            if parsed_quantity > 0:
                draft["quantity"] = parsed_quantity
        except ValueError:
            pass

    unit = str(raw.get("unit") or "").strip().lower()
    if unit in {"kg", "t"}:
        draft["unit"] = unit

    formula_id = _match_named_id(raw.get("formula_id"), raw.get("formula_name"), formulas, "name")
    if formula_id:
        formula = next(item for item in formulas if item.id == formula_id)
        if product_id is None or formula.product_id == product_id:
            draft["formula_id"] = formula_id

    notes = raw.get("extra_notes")
    if isinstance(notes, str) and notes.strip():
        draft["extra_notes"] = notes.strip()[:2000]
    return {key: value for key, value in draft.items() if key in _ALLOWED_FIELDS}


async def extract_order_draft(
    db: AsyncSession,
    text: str,
    image_data_url: str | None = None,
) -> dict[str, Any]:
    image_url = validate_image_data_url(image_data_url) if image_data_url else None
    customers = list((await db.execute(select(Customer).order_by(Customer.company))).scalars().all())
    products = list(
        (
            await db.execute(select(Product).order_by(Product.name))
        ).scalars().all()
    )
    for product in products:
        await db.refresh(product, ["category"])
    formulas = list((await db.execute(select(Formula).order_by(Formula.name))).scalars().all())
    system_prompt = _candidate_prompt(customers, products, formulas)
    user_text = text.strip() or "请从图片中提取订单字段"
    if image_url:
        if not settings.LLM_VISION_MODEL:
            raise HTTPException(503, "图片识别模型尚未配置")
        user_content: Any = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
        model = settings.LLM_VISION_MODEL
    else:
        user_content = user_text
        model = settings.LLM_MODEL
    raw = await _call_model(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        model,
    )
    return _normalize_draft(raw, customers, products, formulas)
