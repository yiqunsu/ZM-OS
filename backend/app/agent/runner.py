"""Drives the LangGraph agent for one turn (or a confirm/cancel resume) and yields
SSE event dicts. Persists display messages + an audit row via its own DB sessions
(the SSE generator outlives the request-scoped session).
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent import skills
from app.agent.graph import MAX_ITERATIONS, get_graph
from app.core.database import async_session
from app.core.logging import logger
from app.models import AgentAuditLog, ChatMessage


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
                            tool_names.extend(tc["name"] for tc in m.tool_calls)

    if interrupt_payload is not None:
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


async def stream_turn(
    session_id: str, user_text: str, user_email: str | None
) -> AsyncGenerator[dict[str, Any], None]:
    skill = skills.resolve_skill(user_text)
    user_msg = await _persist(session_id, role="user", content=user_text)
    graph_input = {"messages": [HumanMessage(content=user_text)], "skill": skill.name}

    meta: dict[str, Any] = {}
    try:
        async for event in _drive(session_id, graph_input, user_msg.id):
            if event["type"] == "__meta__":
                meta = event
                continue
            yield event
    except Exception as err:  # noqa: BLE001
        logger.error("agent_turn_failed", error=str(err), session_id=session_id)
        yield {"type": "error", "error": str(err)}
        return

    await _write_audit(
        session_id, user_email, user_text, skill.name,
        meta.get("tool_names", []), meta.get("usage", {}),
    )


async def stream_resume(
    session_id: str, decision: str, user_email: str | None
) -> AsyncGenerator[dict[str, Any], None]:
    """Resume a graph paused at a write-tool interrupt. decision is 'confirm'|'cancel'."""
    try:
        async for event in _drive(session_id, Command(resume=decision), user_message_id=""):
            if event["type"] == "__meta__":
                continue
            yield event
    except Exception as err:  # noqa: BLE001
        logger.error("agent_resume_failed", error=str(err), session_id=session_id)
        yield {"type": "error", "error": str(err)}
