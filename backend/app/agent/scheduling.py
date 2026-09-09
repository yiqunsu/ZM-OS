"""Bounded scheduling loop. No database, HTTP or UI dependencies."""

import json
from pathlib import Path
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class SchedulingCapabilities(Protocol):
    async def invoke(self, name: str) -> dict[str, Any]: ...


TOOLS = [
    {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }}
    for name, description in (
        ("read_board", "读取当前机器队列和待排订单。"),
        ("read_draft", "读取本会话最新草案，包含人工调整结果。"),
        ("generate_draft", "按现有规则生成排产草案；不会执行生产排产。仅在用户要求生成时调用。"),
    )
]
ALLOWED_TOOLS = {item["function"]["name"] for item in TOOLS}


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int


def build_scheduling_graph(model: Any, capabilities: SchedulingCapabilities):
    prompt = (Path(__file__).parent / "prompt_templates" / "scheduling-v1.md").read_text()
    bound_model = model.bind_tools(TOOLS, parallel_tool_calls=False)

    async def agent(state: State) -> dict:
        reply = await bound_model.ainvoke([SystemMessage(content=prompt), *state["messages"]])
        return {"messages": [reply], "steps": state["steps"] + 1}

    async def tools(state: State) -> dict:
        results = []
        for call in state["messages"][-1].tool_calls:
            if call["name"] not in ALLOWED_TOOLS or call.get("args"):
                result = {"error": "不支持的工具或参数"}
            else:
                result = await capabilities.invoke(call["name"])
            results.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False, default=str),
                tool_call_id=call["id"], name=call["name"],
            ))
        return {"messages": results}

    async def limit(state: State) -> dict:
        return {"messages": [AIMessage(
            content="本轮查询已达到上限，请查看右侧草案或缩小问题范围；尚未执行排产。",
        )]}

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("limit", limit)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", lambda s: (
        "limit" if s["steps"] >= 6 and s["messages"][-1].tool_calls
        else "tools" if s["messages"][-1].tool_calls else END
    ))
    graph.add_edge("tools", "agent")
    graph.add_edge("limit", END)
    return graph.compile()
