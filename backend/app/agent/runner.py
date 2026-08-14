"""Drives the LangGraph agent for one turn (or a confirm/cancel resume) and yields
SSE event dicts. Persists display messages + an audit row via its own DB sessions
(the SSE generator outlives the request-scoped session).
"""

import json
import re
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent import skills
from app.agent.graph import MAX_ITERATIONS, get_graph
from app.agent.runtime import AgentRuntimeError
from app.agent.runtime import openclaw as openclaw_runtime
from app.core.config import settings
from app.core.database import async_session
from app.core.logging import logger
from app.models import AgentAuditLog, ChatMessage, ChatSession
from app.services import chat_attachment_service, order_intake_service, schedule_service

_ORDER_SUBMIT_RE = re.compile(r"下发订单|确认下发|确认创建订单|就这样下单|确认下单")
_SCHEDULE_CONFIRM_RE = re.compile(r"确认排产|确认排单|执行排产|执行排单|就这样排|按方案排")


def _config(session_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MAX_ITERATIONS * 2,
    }


async def _persist(session_id: str, **fields: Any) -> ChatMessage:
    async with async_session() as db:
        msg = ChatMessage(session_id=session_id, **fields)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


def _user_message_committed_event(message: ChatMessage) -> dict[str, Any]:
    return {
        "type": "user_message_committed",
        "user_message_id": message.id,
        "attachments": [
            chat_attachment_service.attachment_metadata(attachment)
            for attachment in message.attachments
        ],
    }


async def _persist_user_message(
    session_id: str,
    user_id: str,
    content: str,
    image_data_url: str | None,
) -> ChatMessage:
    async with async_session() as db:
        return await chat_attachment_service.persist_user_message(
            db,
            session_id,
            user_id,
            content,
            image_data_url,
        )


async def _persist_pending(
    session_id: str,
    name: str,
    args: dict[str, Any],
    display: dict[str, Any],
) -> ChatMessage:
    return await _persist(
        session_id,
        role="assistant",
        content=None,
        tool_calls=[{"name": name, "args": args, "display": display}],
        is_pending=True,
    )


async def _set_workspace(session_id: str, workspace: str | None) -> None:
    async with async_session() as db:
        session = await db.get(ChatSession, session_id)
        if session is not None:
            if session.active_workspace != workspace:
                session.workspace_state = None
            session.active_workspace = workspace
            await db.commit()


async def _get_workspace(session_id: str) -> str | None:
    async with async_session() as db:
        session = await db.get(ChatSession, session_id)
        return session.active_workspace if session is not None else None


async def _merge_order_workspace_draft(session_id: str, draft: dict[str, Any]) -> None:
    async with async_session() as db:
        session = await db.get(ChatSession, session_id)
        if session is None:
            return
        state = session.workspace_state if isinstance(session.workspace_state, dict) else {}
        previous = state.get("order_draft")
        merged = dict(previous) if isinstance(previous, dict) else {}
        previous_spec = merged.get("spec_params")
        incoming_spec = draft.get("spec_params")
        merged.update(draft)
        if isinstance(incoming_spec, dict):
            merged["spec_params"] = {
                **(previous_spec if isinstance(previous_spec, dict) else {}),
                **incoming_spec,
            }
        session.active_workspace = "order_form"
        session.workspace_state = {"order_draft": merged}
        await db.commit()


def _pending_event(user_message_id: str, message: ChatMessage) -> dict[str, Any]:
    tool_call = message.tool_calls[0]
    return {
        "type": "pending_confirmation",
        "user_message_id": user_message_id,
        "assistant_message_id": message.id,
        "tool_call": {
            "id": f"call_{message.id}",
            "name": tool_call["name"],
            "args": tool_call.get("args") or {},
            "display": tool_call.get("display") or {},
        },
    }


async def _write_audit(
    session_id: str, user_email: str | None, prompt: str, skill: str,
    tool_names: list[str], usage: dict[str, int],
) -> None:
    async with async_session() as db:
        db.add(
            AgentAuditLog(
                session_id=session_id,
                user_email=user_email,
                prompt=prompt,
                skill=skill,
                tool_calls=tool_names,
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
        )
        await db.commit()


async def _drive(
    session_id: str,
    graph_input: Any,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Shared streaming loop for both a fresh turn and a resume. Yields SSE events."""
    graph = get_graph()
    config = _config(session_id)

    accumulated = ""
    interrupt_payload: dict[str, Any] | None = None
    pending_form_submit = False
    tool_names: list[str] = []
    usage: dict[str, int] = {}

    async for mode, payload in graph.astream(
        graph_input, config, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            chunk, meta = payload
            if meta.get("langgraph_node") != "agent":
                continue
            if getattr(chunk, "usage_metadata", None):
                usage = chunk.usage_metadata
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                accumulated += text
                yield {"type": "delta", "content": text}
        elif mode == "updates":
            if "__interrupt__" in payload:
                interrupt_payload = payload["__interrupt__"][0].value
            for node, update in payload.items():
                if node == "agent" and update and update.get("messages"):
                    for m in update["messages"]:
                        if isinstance(m, AIMessage) and m.tool_calls:
                            for tc in m.tool_calls:
                                tool_names.append(tc["name"])
                                # 协同录单信号 → 驱动前端表单（表单为唯一数据源）
                                if tc["name"] == "draft_order":
                                    yield {"type": "form_update", "fields": tc.get("args") or {}}
                                elif tc["name"] == "submit_order":
                                    pending_form_submit = True

    if pending_form_submit:
        if accumulated:
            yield {"type": "cancel_delta"}
        assistant_msg = await _persist_pending(
            session_id,
            "submit_order_form",
            {},
            {"message": "确认后将提交右侧表单的当前内容"},
        )
        yield _pending_event(user_message_id, assistant_msg)
    elif interrupt_payload is not None:
        # Write tool paused for confirmation: persist a pending assistant message so
        # the card can be reconstructed on reload, then tell the client to show it.
        if accumulated:
            yield {"type": "cancel_delta"}
        name = interrupt_payload["tool_name"]
        tc = {"function": {"name": name, "arguments": json.dumps(interrupt_payload["args"])}}
        assistant_msg = await _persist(
            session_id, role="assistant", content=None, tool_calls=[tc], is_pending=True
        )
        yield {
            "type": "pending_confirmation",
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_msg.id,
            "tool_call": {
                "id": f"call_{assistant_msg.id}",
                "name": name,
                "args": interrupt_payload["args"],
                "display": interrupt_payload["display"],
            },
        }
    else:
        assistant_msg = await _persist(session_id, role="assistant", content=accumulated)
        yield {
            "type": "text_done",
            "message_id": assistant_msg.id,
            "user_message_id": user_message_id,
        }

    return_meta = {"tool_names": tool_names, "usage": usage}
    yield {"type": "__meta__", **return_meta}


async def _stream_langgraph_turn(
    session_id: str,
    user_text: str,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    skill = skills.resolve_skill(user_text)
    graph_input = {"messages": [HumanMessage(content=user_text)], "skill": skill.name}

    # 录单意图 → 让前端打开右侧「录入订单」表单（对话随即变窄）
    if skill.name == "create-order":
        yield {"type": "panel", "panel": "order_form", "action": "open"}

    meta: dict[str, Any] = {}
    try:
        async for event in _drive(session_id, graph_input, user_message_id):
            if event["type"] == "__meta__":
                meta = event
                continue
            yield event
    except Exception as err:  # noqa: BLE001
        logger.error(
            "agent_turn_failed",
            runtime="langgraph",
            error_type=type(err).__name__,
            session_id=session_id,
        )
        yield {
            "type": "error",
            "error": "AI 助手暂时不可用，请稍后重试",
            "user_message_id": user_message_id,
        }
        return

    await _write_audit(
        session_id, user_email, user_text, skill.name,
        meta.get("tool_names", []), meta.get("usage", {}),
    )


async def _stream_openclaw_turn(
    session_id: str,
    user_text: str,
    user_id: str,
    user_email: str | None,
    user_message_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    if user_message_id is None:
        user_message_id = (await _persist(session_id, role="user", content=user_text)).id
    accumulated = ""
    usage: dict[str, int] = {}

    try:
        async for event in openclaw_runtime.stream_text(session_id, user_id, user_text):
            if event.type == "delta":
                accumulated += event.content
                yield {"type": "delta", "content": event.content}
            elif event.type == "completed":
                usage = event.usage
    except AgentRuntimeError as err:
        yield {"type": "error", "error": str(err), "user_message_id": user_message_id}
        return
    except Exception as err:  # noqa: BLE001
        logger.error(
            "agent_turn_failed",
            runtime="openclaw",
            error_type=type(err).__name__,
            session_id=session_id,
        )
        yield {
            "type": "error",
            "error": "AI 助手暂时不可用，请稍后重试",
            "user_message_id": user_message_id,
        }
        return

    assistant_msg = await _persist(session_id, role="assistant", content=accumulated)
    yield {
        "type": "text_done",
        "message_id": assistant_msg.id,
        "user_message_id": user_message_id,
    }
    await _write_audit(
        session_id,
        user_email,
        user_text,
        "openclaw-text",
        [],
        usage,
    )


async def _stream_order_intake(
    session_id: str,
    user_text: str,
    image_data_url: str | None,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    await _set_workspace(session_id, "order_form")
    persisted_text = user_text or "[图片订单]"
    yield {"type": "panel", "panel": "order_form", "action": "open"}
    try:
        async with async_session() as db:
            draft = await order_intake_service.extract_order_draft(
                db, user_text, image_data_url
            )
    except Exception as err:  # HTTPException is converted to a safe SSE message below.
        from fastapi import HTTPException

        if isinstance(err, HTTPException):
            yield {
                "type": "error",
                "error": str(err.detail),
                "user_message_id": user_message_id,
            }
        else:
            logger.error(
                "order_intake_failed",
                error_type=type(err).__name__,
                session_id=session_id,
            )
            yield {
                "type": "error",
                "error": "订单信息识别失败，请重试",
                "user_message_id": user_message_id,
            }
        return

    if draft:
        await _merge_order_workspace_draft(session_id, draft)
        yield {"type": "form_update", "fields": draft}
        response_text = "已把识别到的订单信息填入右侧表单，请核对后下发。"
    else:
        response_text = "暂未识别到明确字段，请补充客户、产品、规格或数量。"
    assistant_msg = await _persist(session_id, role="assistant", content=response_text)
    yield {"type": "delta", "content": response_text}
    yield {
        "type": "text_done",
        "message_id": assistant_msg.id,
        "user_message_id": user_message_id,
    }
    await _write_audit(
        session_id,
        user_email,
        persisted_text,
        "controlled-order-intake",
        ["extract_order_draft"],
        {},
    )


async def _stream_schedule_plan(
    session_id: str,
    user_text: str,
    user_id: str,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    try:
        async with async_session() as db:
            plan = await schedule_service.create_schedule_plan(db, session_id, user_id)
    except Exception as err:  # noqa: BLE001
        logger.error(
            "schedule_plan_failed",
            error_type=type(err).__name__,
            session_id=session_id,
        )
        yield {
            "type": "error",
            "error": "排产草案生成失败，请稍后重试",
            "user_message_id": user_message_id,
        }
        return

    await _set_workspace(session_id, "schedule_plan")
    payload = {
        "id": plan.id,
        "status": plan.status.value,
        "tasks": plan.tasks,
        "unassigned": plan.unassigned,
        "created_at": plan.created_at.isoformat(),
    }
    yield {"type": "panel", "panel": "schedule_plan", "action": "open"}
    yield {"type": "schedule_plan", "plan": payload}
    response_text = (
        f"已生成确定性排产草案：{len(plan.tasks)} 个任务，"
        f"{len(plan.unassigned)} 张订单暂未排入。请在右侧核对；需要执行时告诉我“确认排产”。"
    )
    assistant_msg = await _persist(session_id, role="assistant", content=response_text)
    yield {"type": "delta", "content": response_text}
    yield {
        "type": "text_done",
        "message_id": assistant_msg.id,
        "user_message_id": user_message_id,
    }
    await _write_audit(
        session_id,
        user_email,
        user_text,
        "deterministic-schedule",
        ["create_schedule_plan"],
        {},
    )


async def _stream_order_submit_confirmation(
    session_id: str,
    user_text: str,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    pending = await _persist_pending(
        session_id,
        "submit_order_form",
        {},
        {"message": "确认后将提交右侧表单的当前内容"},
    )
    yield _pending_event(user_message_id, pending)
    await _write_audit(
        session_id, user_email, user_text, "order-submit-confirmation", [], {}
    )


async def _stream_missing_order_workspace(
    session_id: str,
    user_text: str,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    response_text = "当前没有打开的订单表单，请先告诉我要录入的订单信息。"
    assistant_msg = await _persist(session_id, role="assistant", content=response_text)
    yield {"type": "delta", "content": response_text}
    yield {
        "type": "text_done",
        "message_id": assistant_msg.id,
        "user_message_id": user_message_id,
    }
    await _write_audit(
        session_id, user_email, user_text, "order-submit-without-workspace", [], {}
    )


async def _stream_schedule_confirmation(
    session_id: str,
    user_text: str,
    user_id: str,
    user_email: str | None,
    user_message_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    async with async_session() as db:
        plan = await schedule_service.get_latest_draft(db, session_id, user_id)
    if plan is None:
        response_text = "当前对话没有可确认的排产草案，请先让我生成排产方案。"
        assistant_msg = await _persist(session_id, role="assistant", content=response_text)
        yield {"type": "delta", "content": response_text}
        yield {
            "type": "text_done",
            "message_id": assistant_msg.id,
            "user_message_id": user_message_id,
        }
        return
    pending = await _persist_pending(
        session_id,
        "execute_schedule_plan",
        {"plan_id": plan.id},
        {
            "plan_id": plan.id,
            "task_count": len(plan.tasks),
            "order_count": sum(len(task["order_ids"]) for task in plan.tasks),
        },
    )
    yield _pending_event(user_message_id, pending)
    await _write_audit(
        session_id, user_email, user_text, "schedule-confirmation", [], {}
    )


async def stream_turn(
    session_id: str,
    user_text: str,
    user_id: str,
    user_email: str | None,
    image_data_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    persisted_text = user_text or "[图片订单]"
    try:
        user_message = await _persist_user_message(
            session_id,
            user_id,
            persisted_text,
            image_data_url,
        )
    except Exception as err:  # Validation/storage failures happen before acceptance.
        from fastapi import HTTPException

        if isinstance(err, HTTPException):
            error_message = str(err.detail)
        else:
            logger.error(
                "chat_user_message_persist_failed",
                error_type=type(err).__name__,
                session_id=session_id,
            )
            error_message = "消息保存失败，请重试"
        yield {"type": "error", "error": error_message}
        return

    user_message_id = user_message.id
    yield _user_message_committed_event(user_message)

    workspace = await _get_workspace(session_id)
    if _ORDER_SUBMIT_RE.search(user_text):
        stream = (
            _stream_order_submit_confirmation(
                session_id,
                user_text,
                user_email,
                user_message_id,
            )
            if workspace == "order_form"
            else _stream_missing_order_workspace(
                session_id,
                user_text,
                user_email,
                user_message_id,
            )
        )
        async for event in stream:
            yield event
        return

    if _SCHEDULE_CONFIRM_RE.search(user_text):
        async for event in _stream_schedule_confirmation(
            session_id,
            user_text,
            user_id,
            user_email,
            user_message_id,
        ):
            yield event
        return

    skill = skills.resolve_skill(user_text)
    if skill.name == "schedule":
        async for event in _stream_schedule_plan(
            session_id,
            user_text,
            user_id,
            user_email,
            user_message_id,
        ):
            yield event
        return

    if image_data_url or skill.name == "create-order" or workspace == "order_form":
        async for event in _stream_order_intake(
            session_id,
            user_text,
            image_data_url,
            user_email,
            user_message_id,
        ):
            yield event
        return

    if settings.AGENT_RUNTIME == "openclaw":
        async for event in _stream_openclaw_turn(
            session_id,
            user_text,
            user_id,
            user_email,
            user_message_id,
        ):
            yield event
        return

    async for event in _stream_langgraph_turn(
        session_id,
        user_text,
        user_email,
        user_message_id,
    ):
        yield event


async def stream_resume(
    session_id: str, decision: str, user_email: str | None
) -> AsyncGenerator[dict[str, Any], None]:
    """Resume a graph paused at a write-tool interrupt. decision is 'confirm'|'cancel'."""
    if settings.AGENT_RUNTIME != "langgraph":
        yield {"type": "error", "error": "当前 Agent 运行时没有待恢复的操作"}
        return
    try:
        async for event in _drive(session_id, Command(resume=decision), user_message_id=""):
            if event["type"] == "__meta__":
                continue
            yield event
    except Exception as err:  # noqa: BLE001
        logger.error(
            "agent_resume_failed",
            runtime="langgraph",
            error_type=type(err).__name__,
            session_id=session_id,
        )
        yield {"type": "error", "error": "AI 助手暂时不可用，请稍后重试"}
