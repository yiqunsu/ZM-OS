"""Trusted identity-bound capabilities for the order graph."""

import asyncio
import base64
import json

from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import Field, ValidationError
from sqlalchemy import select

from app.agent.model_transport import VisionError, call_vision_model, content_text
from app.agent.specialized import prompts
from app.agent.specialized.admission import Admission
from app.agent.specialized.model_io import ModelIO
from app.agent.worker import LeaseLost, RunContext, lock_run
from app.core.database import async_session
from app.models import ChatAttachment, ChatMessage, ChatSession, OrderIntakeItem
from app.schemas.agent import AgentInput
from app.schemas.agent.entity_matching import extraction_schema
from app.schemas.agent.order_extraction import ScreenshotExtraction
from app.schemas.agent.order_intake import DraftPatch
from app.services import order_intake_item_service as intake
from app.services import order_matching_service as matching
from app.services import order_recognition_service as recognition
from app.services.agent_event_service import append_event
from app.services.agent_projections import item_snapshot
from app.services.agent_tool_service import perform_tool
from app.services.chat_attachment_service import _storage_path


class SearchArgs(AgentInput):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=10)


TOOL_SCHEMAS = {
    "read_current_draft": (AgentInput, "读取当前订单最新草稿、字段问题和revision"),
    "search_customers": (SearchArgs, "搜索已有客户，不创建客户"),
    "search_products": (SearchArgs, "搜索已有产品，不创建产品"),
    "search_formulas": (SearchArgs, "搜索已有配方；仅选择与当前产品相符的配方"),
    "patch_current_draft": (DraftPatch, "用expected_revision保护地补充当前订单草稿，不创建正式订单"),
}
TOOLS = [
    {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema.model_json_schema()},
    }
    for name, (schema, description) in TOOL_SCHEMAS.items()
]


def compact_item(item: dict | None) -> dict | None:
    if item is None:
        return None
    draft = dict(item.get("draft") or {})
    draft["spec_params"] = {key: str(value)[:80] for key, value in draft.get("spec_params", {}).items()}
    draft["extra_notes"] = str(draft.get("extra_notes", ""))[:300]
    return {
        "id": item["id"],
        "revision": item["revision"],
        "status": item["status"],
        "draft": draft,
        "recognition_status": item["recognition_status"],
        "issues": [
            {
                "field": issue.get("field"),
                "code": issue.get("code"),
                "message": str(issue.get("message", ""))[:120],
            }
            for issue in item.get("issues", [])[:10]
        ],
        "display_values_may_be_truncated": True,
    }


class OrderCapabilities(ModelIO):
    def __init__(
        self, context: RunContext, *, sessions=async_session, model=None, vision_call=call_vision_model
    ):
        super().__init__(context, sessions=sessions, model=model)
        self.vision_call = vision_call

    async def load(self) -> dict:
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            item = await db.get(OrderIntakeItem, run.work_item_id) if run.work_item_id else None
            ids = [run.trigger_message_id]
            if item:
                ids.append(item.source_message_id)
            query = select(ChatMessage).where(
                ChatMessage.session_id == session.id,
                ChatMessage.event_seq <= run.input_event_seq,
                (ChatMessage.work_item_id == run.work_item_id) | ChatMessage.id.in_(ids),
            )
            rows = (await db.scalars(query.order_by(ChatMessage.event_seq.desc()).limit(50))).all()
            messages, used_ids, bytes_used = [], [], 0
            for row in rows:
                if not row.content:
                    continue
                content = row.content[:2000]
                size = len(content.encode())
                if bytes_used + size > 7000:
                    break
                messages.append(
                    AIMessage(content=content) if row.role == "assistant" else HumanMessage(content=content)
                )
                used_ids.append(row.id)
                bytes_used += size
            messages.reverse()
            trigger = await db.get(ChatMessage, run.trigger_message_id) if run.trigger_message_id else None
            loaded = {
                "item": item_snapshot(item) if item else None,
                "messages": messages,
                "input_text": trigger.content if trigger else "",
                "queued_only": run.config_snapshot.get("queued_only", False),
                "trigger_kind": run.trigger_kind,
                "workbench": run.config_snapshot.get("intake_workbench", False),
                "vision_model_id": run.config_snapshot["vision_model_id"],
            }
            run.context_snapshot = {
                "schema_version": 1,
                "message_ids": list(reversed(used_ids)),
                "work_item_id": run.work_item_id,
                "work_item_revision": item.revision if item else None,
                "input_event_seq": run.input_event_seq,
                "truncated_message_count": len(rows) - len(messages),
                "usage_complete": True,
            }
            await db.commit()
            self.loaded = loaded
            return loaded

    async def admit(self, loaded: dict) -> dict:
        if loaded["trigger_kind"] in {"NEXT_ITEM", "RESUME_ITEM"}:
            result = Admission(decision="ALLOW", reason_code="IN_SCOPE")
        else:
            result = await self.admit_input(
                {
                    "agent_type": "ORDER_INTAKE",
                    "input": loaded["input_text"][:2000],
                    "has_image": loaded["item"] is not None or loaded["queued_only"],
                    "has_current_item": loaded["item"] is not None,
                    "current_draft": compact_item(loaded["item"]),
                }
            )
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            append_event(db, session, "admittance.decided", result.model_dump(), run_id=run.id)
            await db.commit()
        return result.model_dump()

    async def recognize(self, loaded: dict) -> dict:
        item = loaded["item"]
        async with self.sessions() as db:
            await lock_run(db, self.context)
            attachment = await db.get(ChatAttachment, item["source_attachment_id"])
            if not attachment or not attachment.available or attachment.session_id != self.context.session_id:
                raise RuntimeError("source image unavailable")
            path, mime = _storage_path(attachment.storage_key), attachment.mime_type
            source = await db.get(ChatMessage, item["source_message_id"])
            source_text = source.content or "请识别截图订单"
            catalog = await matching.vision_catalog(db)
        image = await asyncio.to_thread(path.read_bytes)
        image_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        schema = extraction_schema(catalog)
        system = prompts.EXTRACTION + "\nSchema:" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"catalog": catalog, "message": source_text[:2000]}, ensure_ascii=False
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        raw = None
        for attempt in range(2):
            await self.count_model("EXTRACTING")
            # Direct multimodal HTTP avoids putting image bytes into LangChain/Phoenix traces.
            try:
                response = await self.vision_call(messages, loaded["vision_model_id"])
                raw = schema.model_validate(response)
                break
            except VisionError as error:
                await self.recognition_diagnostic(error.code, attempt)
                if error.code not in {"JSON_INVALID", "RESPONSE_INVALID", "OUTPUT_TRUNCATED"} or attempt:
                    await self._recognition_failed(error.code)
                    raise RuntimeError("extraction unavailable") from None
                messages[0]["content"] = system + "\n请修正上一轮输出，仅返回完整且符合Schema的JSON。"
            except (ValidationError, HTTPException) as error:
                await self.recognition_diagnostic("SCHEMA_INVALID", attempt)
                if attempt:
                    # Bad choices must not discard valid measurements. Strip only choice fields.
                    if isinstance(error, ValidationError) and all(
                        any(part in {"customer_match", "product_match"} for part in e["loc"])
                        for e in error.errors()
                    ):
                        sanitized = {**response, "orders": [dict(order) for order in response["orders"]]}
                        affected = set()
                        for detail in error.errors():
                            index, field = detail["loc"][1:3]
                            sanitized["orders"][index][field] = None
                            affected.add(index)
                        raw = ScreenshotExtraction.model_validate(sanitized)
                        for index in affected:
                            raw.orders[index].warnings.append(
                                "客户或产品选择格式无效，其他信息已保留，请手动核对。"
                            )
                        break
                    await self._recognition_failed()
                    raise RuntimeError("extraction invalid") from None
                errors = (
                    [
                        {"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                        for e in error.errors(include_input=False, include_url=False)[:8]
                    ]
                    if isinstance(error, ValidationError)
                    else [{"type": "invalid_json_response"}]
                )
                messages[0]["content"] = (
                    system
                    + "\n上一次输出未符合Schema，请修正以下字段；数值不能带引号或单位："
                    + json.dumps(errors, ensure_ascii=False)
                )
        await self.usage(None)
        suggestions, decisions = matching.visual_suggestions(raw, catalog)
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            run.context_snapshot = {
                **run.context_snapshot,
                "screenshot_context": raw.context_text,
                "entity_matching": decisions,
                "catalog_manual_fields": catalog["manual_fields"],
            }
            append_event(
                db, session, "run.progress", {"stage": "MATCHING", "decisions": decisions}, run_id=run.id
            )
            await db.commit()
        if catalog["manual_fields"]:
            for order in raw.orders:
                order.warnings.append("部分基础资料候选较多，请手动选择对应客户或产品。")

        async def save(db):
            session = await db.get(ChatSession, self.context.session_id)
            current = await db.get(OrderIntakeItem, self.context.work_item_id)
            return await recognition.save_screenshot_extraction(
                db, session, current, raw, item["revision"], self.context.run_id, suggestions=suggestions
            )

        try:
            return await perform_tool(
                self.sessions,
                self.context,
                call_key="extract_order",
                tool_name="extract_order",
                args={"expected_revision": item["revision"]},
                allowed_tools=frozenset({"extract_order"}),
                operation=save,
            )
        except HTTPException as error:
            if (
                not loaded["workbench"]
                and isinstance(error.detail, dict)
                and error.detail.get("code") == "DRAFT_REVISION_CONFLICT"
            ):
                return await self._current_item()
            raise

    async def recognition_diagnostic(self, code: str, attempt: int):
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            append_event(
                db,
                session,
                "run.progress",
                {
                    "stage": "RECOGNITION_ERROR",
                    "code": code,
                    "attempt": attempt + 1,
                },
                run_id=run.id,
            )
            await db.commit()

    async def _recognition_failed(self, code="EXTRACTION_INVALID"):
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            item = await db.get(OrderIntakeItem, self.context.work_item_id)
            item.recognition_status, item.last_error_code = "FAILED", code
            item.revision += 1
            append_event(
                db,
                session,
                "recognition.failed",
                {"error_code": code},
                run_id=run.id,
                work_item_id=item.id,
            )
            await db.commit()

    async def _current_item(self):
        async with self.sessions() as db:
            await lock_run(db, self.context)
            return item_snapshot(await db.get(OrderIntakeItem, self.context.work_item_id))

    async def main(self, messages: list, loaded: dict):
        await self.count_model("DRAFTING")
        model = await self._model()
        if self.bound_model is None:
            self.bound_model = model.bind_tools(TOOLS, parallel_tool_calls=False)
        context = json.dumps(
            {
                "current_item": compact_item(await self._current_item()),
                "just_recognized": loaded.get("just_recognized", False),
                "recognized_order_count": loaded["item"].get("recognized_order_count"),
            },
            ensure_ascii=False,
        )
        reply = await self.bound_model.ainvoke(self.bounded_messages(prompts.ORDER_SKILL + context, messages))
        await self.usage(reply)
        return reply

    async def tool(self, call: dict) -> dict:
        try:
            name = call["name"]
            if name not in TOOL_SCHEMAS:
                return {"error_code": "TOOL_NOT_ALLOWED", "message": "此助手不能使用该工具"}
            parsed = TOOL_SCHEMAS[name][0].model_validate(call.get("args", {})).model_dump()

            async def operation(db):
                if name.startswith("search_"):
                    return {
                        "candidates": await matching.search_existing(
                            db, name.removeprefix("search_"), **parsed
                        )
                    }
                from app.models import ChatSession

                session = await db.get(ChatSession, self.context.session_id)
                item = await db.get(OrderIntakeItem, self.context.work_item_id)
                if name == "read_current_draft":
                    return item_snapshot(item)
                return await intake.patch_draft(
                    db,
                    session,
                    item,
                    parsed["expected_revision"],
                    parsed["patch"],
                    source="USER",
                    run_id=self.context.run_id,
                )

            result = await perform_tool(
                self.sessions,
                self.context,
                call_key=call["id"],
                tool_name=name,
                args=parsed,
                allowed_tools=frozenset(TOOL_SCHEMAS),
                operation=operation,
            )
            return compact_item(result) if "draft" in result else result
        except LeaseLost:
            raise
        except (ValidationError, HTTPException) as error:
            code = (
                error.detail.get("code", "TOOL_FAILED")
                if isinstance(error, HTTPException) and isinstance(error.detail, dict)
                else "INPUT_INVALID"
            )
            return {"error_code": code, "message": "工具未修改草稿，请读取最新版本或补充有效字段"}

    async def compose(self, messages: list, loaded: dict) -> str:
        await self.count_model("EXPLAINING")
        facts = {
            "current_item": compact_item(await self._current_item()),
            "screenshot_order_count": loaded["item"].get("recognized_order_count"),
            "input": loaded["input_text"][:2000],
            "tool_results": [
                content_text(message.content)[:1500]
                for message in messages
                if getattr(message, "type", "") == "tool"
            ][-5:],
        }
        return await self.stream_response(prompts.COMPOSE + prompts.ORDER_COMPOSE, facts)
