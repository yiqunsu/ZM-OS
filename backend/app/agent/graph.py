"""LangGraph agent: intent-routed, tool-calling loop with human-in-the-loop
interrupts on write operations, state persisted in a Postgres checkpointer.

Graph shape:
    START → agent → (tool_calls?) → tools → agent → … → END
                         └── no tool_calls ──────────→ END

Write tools (create order / execute schedule) call `interrupt()` in the tools
node, pausing the graph until the frontend confirms via `Command(resume=…)`.
Read tools execute immediately and loop back to the model.
"""

import json
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent import prompts, skills
from app.agent.tools import WRITE_TOOLS, enrich_for_display, run_read_tool, run_write_tool, schemas_for
from app.core.config import settings

MAX_ITERATIONS = 8  # mirrors the original agentic-loop cap


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    skill: str


def _build_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        max_tokens=2048,
        temperature=0.3,
    )


async def _agent_node(state: AgentState) -> dict[str, Any]:
    skill = skills.get_skill(state.get("skill") or "general")
    context = await skills.load_context(skill)
    system = prompts.system_prompt() + "\n\n" + skill.task_prompt + context

    # parallel_tool_calls=False asks the model for one call per turn, but DeepSeek
    # ignores it and still emits parallel calls — so the real guard is _tools_node,
    # which answers *every* tool_call. We keep the hint for providers that honor it.
    model = _build_model().bind_tools(schemas_for(skill.allowed_tools), parallel_tool_calls=False)
    response = await model.ainvoke([SystemMessage(content=system), *state["messages"]])
    return {"messages": [response]}


async def _tools_node(state: AgentState) -> dict[str, Any]:
    # Answer EVERY tool_call on the message: DeepSeek emits parallel calls, and the
    # OpenAI protocol requires one tool message per tool_call_id — leaving any
    # unanswered makes the next model turn fail with "insufficient tool messages".
    last = state["messages"][-1]
    out: list[ToolMessage] = []
    for tool_call in last.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]
        tc_id = tool_call["id"]

        if name in WRITE_TOOLS:
            # `interrupt()` is the first side-effecting call. On resume the node
            # re-runs from the top, so read calls above and enrich (read-only/
            # idempotent) re-running is harmless.
            display = await enrich_for_display(name, args)
            decision = interrupt({"tool_name": name, "args": args, "display": display})
            if decision == "confirm":
                result = await run_write_tool(name, args)
            else:
                result = {"cancelled": True, "message": "老板取消了操作"}
        else:
            result = await run_read_tool(name, args)

        content = json.dumps(result, ensure_ascii=False, default=str)
        out.append(ToolMessage(content=content, tool_call_id=tc_id, name=name))
    return {"messages": out}


def _route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def _build_uncompiled() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("agent", _agent_node)
    g.add_node("tools", _tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g


# ─── Checkpointer + compiled graph lifecycle (managed by the FastAPI lifespan)──

_pool: AsyncConnectionPool | None = None
_graph = None


async def init_agent() -> None:
    global _pool, _graph
    _pool = AsyncConnectionPool(
        conninfo=settings.checkpointer_dsn,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
        max_size=10,
    )
    await _pool.open()
    checkpointer = AsyncPostgresSaver(_pool)
    await checkpointer.setup()
    _graph = _build_uncompiled().compile(checkpointer=checkpointer)


async def close_agent() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_graph():
    if _graph is None:
        raise RuntimeError("Agent graph not initialized — call init_agent() at startup")
    return _graph
