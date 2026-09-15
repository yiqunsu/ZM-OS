"""Scheduling graph: explain existing facts or prepare one proposal, never execute it."""

import json
from typing import Annotated, TypedDict

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.limits import MAX_MAIN_CALLS
from app.agent.worker import RunOutcome, RunResult


class State(TypedDict):
    loaded: dict
    admission: dict
    messages: Annotated[list, add_messages]
    steps: int
    result: RunResult
    outcome: str


def build_scheduling_graph(capabilities):
    async def load_context(state):
        loaded = await capabilities.load()
        return {"loaded": loaded, "messages": loaded["messages"], "steps": 0, "outcome": "ANSWERED"}

    async def admittance(state):
        return {"admission": await capabilities.admit(state["loaded"])}

    def route(state):
        admission = state["admission"]
        if admission["decision"] != "ALLOW" or admission["requested_operation"] in {
            "EXECUTE_REQUEST",
            "ADJUST_REQUEST",
        }:
            return "explain_scope"
        if admission["requested_operation"] == "GENERATE":
            return "generate_plan"
        return "main_agent"

    async def explain_scope(state):
        decision, operation = state["admission"]["decision"], state["admission"]["requested_operation"]
        if decision == "OUT_OF_SCOPE":
            result = RunResult(
                "本会话只协助排单。录入订单请进入录单助手；维护基础数据请前往对应页面。",
                RunOutcome.OUT_OF_SCOPE,
            )
        elif operation == "EXECUTE_REQUEST":
            result = RunResult(
                "请先核对右侧最新草案，再点击确认排单。对话不会直接下发生产。", RunOutcome.NEEDS_INPUT
            )
        elif operation == "ADJUST_REQUEST":
            result = RunResult(
                "请在右侧草案中调整机器、订单分组和顺序，保存后再确认排单。", RunOutcome.NEEDS_INPUT
            )
        else:
            result = RunResult("请说明需要查询当前生产情况，还是生成新的排单建议。", RunOutcome.NEEDS_INPUT)
        return {"result": result}

    async def generate_plan(state):
        result = await capabilities.generate()
        if result.get("error_code"):
            return {
                "result": RunResult("草案生成未完成，请核对当前版本后重试。", RunOutcome.NEEDS_INPUT),
                "outcome": "REPLACEMENT_REQUIRED",
            }
        if result.get("outcome") == "NO_PENDING":
            return {
                "result": RunResult("当前没有待排单的订单，暂时无法生成排单建议。", RunOutcome.NO_PENDING),
                "outcome": "NO_PENDING",
            }
        if result.get("replacement_required"):
            return {
                "result": RunResult(
                    "已有一份待核对草案。如需重新生成，请先在右侧确认替换当前草案。", RunOutcome.NEEDS_INPUT
                ),
                "outcome": "REPLACEMENT_REQUIRED",
            }
        return {"outcome": result.get("outcome", "DRAFT_READY")}

    async def explain_workbench(state):
        return {"result": RunResult(await capabilities.explain_workbench(), RunOutcome(state["outcome"]))}

    async def main_agent(state):
        reply = await capabilities.main(state["messages"], state["loaded"])
        return {"messages": [reply], "steps": state["steps"] + 1}

    async def tools(state):
        messages = []
        for call in state["messages"][-1].tool_calls:
            result = await capabilities.tool(call)
            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
            )
        return {"messages": messages}

    async def compose_response(state):
        text = await capabilities.compose(state["messages"], state["loaded"])
        outcome = (
            "LIMIT_REACHED"
            if state["steps"] >= MAX_MAIN_CALLS and state["messages"][-1].tool_calls
            else state["outcome"]
        )
        return {"result": RunResult(text, RunOutcome(outcome))}

    graph = StateGraph(State)
    for name, node in (
        ("load_context", load_context),
        ("admittance", admittance),
        ("explain_scope", explain_scope),
        ("generate_plan", generate_plan),
        ("main_agent", main_agent),
        ("explain_workbench", explain_workbench),
        ("tools", tools),
        ("compose_response", compose_response),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context", lambda state: "generate_plan" if state["loaded"].get("workbench") else "admittance"
    )
    graph.add_conditional_edges("admittance", route)
    graph.add_conditional_edges(
        "generate_plan",
        lambda state: END
        if state["outcome"] in {"NO_PENDING", "REPLACEMENT_REQUIRED"}
        else ("explain_workbench" if state["loaded"].get("workbench") else "main_agent"),
    )
    graph.add_conditional_edges(
        "main_agent",
        lambda state: "tools"
        if state["messages"][-1].tool_calls and state["steps"] < MAX_MAIN_CALLS
        else "compose_response",
    )
    graph.add_edge("tools", "main_agent")
    graph.add_edge("explain_scope", END)
    graph.add_edge("compose_response", END)
    graph.add_edge("explain_workbench", END)
    return graph.compile()
