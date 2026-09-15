"""Order intake graph; persistence, model and tool effects are injected capabilities."""

import json
from typing import Annotated, Protocol, TypedDict

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.limits import MAX_MAIN_CALLS
from app.agent.worker import RunOutcome, RunResult


class OrderCapabilities(Protocol):
    async def load(self) -> dict: ...
    async def admit(self, loaded: dict) -> dict: ...
    async def recognize(self, loaded: dict) -> dict: ...
    async def main(self, messages: list, loaded: dict): ...
    async def tool(self, call: dict) -> dict: ...
    async def compose(self, messages: list, loaded: dict) -> str: ...


class State(TypedDict):
    loaded: dict
    admission: dict
    messages: Annotated[list, add_messages]
    steps: int
    result: RunResult


def build_order_graph(capabilities: OrderCapabilities):
    async def load_context(state):
        loaded = await capabilities.load()
        return {"loaded": loaded, "messages": loaded["messages"], "steps": 0}

    async def admittance(state):
        return {"admission": await capabilities.admit(state["loaded"])}

    def route(state):
        if state["admission"]["decision"] != "ALLOW":
            return "explain_scope"
        if state["loaded"]["queued_only"]:
            return "queue_ack"
        if state["loaded"]["item"] is None:
            return "request_image"
        if state["loaded"]["item"]["recognition_status"] != "SUCCEEDED":
            return "extract_order"
        return "main_agent"

    async def explain_scope(state):
        if state["admission"]["decision"] == "CLARIFY":
            return {"result": RunResult("请说明需要补充或核对当前订单的哪些信息。", RunOutcome.NEEDS_INPUT)}
        return {
            "result": RunResult(
                "本会话只协助录入订单。排单请进入智能排单助手；维护客户、产品或配方请前往对应页面。",
                RunOutcome.OUT_OF_SCOPE,
            )
        }

    async def queue_ack(state):
        return {
            "result": RunResult(
                "新截图已加入待处理队列。我们一个一个来，先核对当前订单。", RunOutcome.QUEUED_ONLY
            )
        }

    async def request_image(state):
        return {
            "result": RunResult(
                "请上传订单聊天截图，同图多笔订单会分别生成草稿；也可以从列表恢复暂放的订单。",
                RunOutcome.NEEDS_INPUT,
            )
        }

    async def extract_order(state):
        item = await capabilities.recognize(state["loaded"])
        return {"loaded": {**state["loaded"], "item": item, "just_recognized": True}}

    async def main_agent(state):
        reply = await capabilities.main(state["messages"], state["loaded"])
        return {"messages": [reply], "steps": state["steps"] + 1}

    async def tools(state):
        results = []
        for call in state["messages"][-1].tool_calls:
            result = await capabilities.tool(call)
            results.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
            )
        return {"messages": results}

    async def compose_response(state):
        text = await capabilities.compose(state["messages"], state["loaded"])
        limited = state["steps"] >= MAX_MAIN_CALLS and bool(state["messages"][-1].tool_calls)
        return {"result": RunResult(text, RunOutcome.LIMIT_REACHED if limited else RunOutcome.DRAFT_READY)}

    async def draft_ready(state):
        return {"result": RunResult("截图识别完成，请对照原图核对订单。", RunOutcome.DRAFT_READY)}

    graph = StateGraph(State)
    graph.add_node("draft_ready", draft_ready)
    graph.add_edge("draft_ready", END)
    for name, node in (
        ("load_context", load_context),
        ("admittance", admittance),
        ("explain_scope", explain_scope),
        ("queue_ack", queue_ack),
        ("request_image", request_image),
        ("extract_order", extract_order),
        ("main_agent", main_agent),
        ("tools", tools),
        ("compose_response", compose_response),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context",
        lambda state: (
            "extract_order"
            if state["loaded"]["item"] and state["loaded"]["item"]["recognition_status"] != "SUCCEEDED"
            else "draft_ready"
        )
        if state["loaded"].get("workbench")
        else "admittance",
    )
    graph.add_conditional_edges("admittance", route)
    graph.add_conditional_edges(
        "extract_order", lambda state: "draft_ready" if state["loaded"].get("workbench") else "main_agent"
    )
    graph.add_conditional_edges(
        "main_agent",
        lambda state: "tools"
        if state["messages"][-1].tool_calls and state["steps"] < MAX_MAIN_CALLS
        else "compose_response",
    )
    graph.add_edge("tools", "main_agent")
    for name in ("compose_response", "explain_scope", "queue_ack", "request_image"):
        graph.add_edge(name, END)
    return graph.compile()
