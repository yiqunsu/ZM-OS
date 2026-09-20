"""Code-owned graph registry, shared by the API and worker release."""

from app.agent.limits import (
    CONTEXT_TOKEN_BUDGET,
    MAX_CONTEXT_TEXT_BYTES,
    MAX_MAIN_CALLS,
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
)
from app.agent.specialized.prompts import prompt_versions
from app.agent.worker import RunContext, RunResult
from app.core.config import settings

GRAPH_VERSION = "v2-2026-09-15-02"


def configuration() -> dict:
    return {
        "schema_version": 1,
        "model_id": settings.LLM_MODEL,
        "vision_model_id": settings.LLM_VISION_MODEL,
        "admittance_model_id": settings.LLM_MODEL,
        "prompt_versions": prompt_versions(),
        "skill_versions": {"order_intake": "2", "scheduling": "1"},
        "tool_registry_version": "1",
        "run_timeout_seconds": 180,
        "queue_timeout_seconds": 120,
        "limits": {
            "model_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "run_timeout_seconds": 180,
            "max_main_calls": MAX_MAIN_CALLS,
            "max_tools": MAX_TOOL_CALLS,
            "context_tokens": CONTEXT_TOKEN_BUDGET,
            "max_model_calls": MAX_MODEL_CALLS,
            "context_text_bytes": MAX_CONTEXT_TEXT_BYTES,
        },
        "retry_intent": None,
    }


async def execute_order(context: RunContext) -> RunResult:
    from app.agent.specialized.order_capabilities import OrderCapabilities
    from app.agent.specialized.order_graph import build_order_graph

    graph = build_order_graph(OrderCapabilities(context))
    final = await graph.ainvoke({}, config={"recursion_limit": 40})
    return final["result"]


async def execute_scheduling(context: RunContext) -> RunResult:
    from app.agent.specialized.scheduling_capabilities import SchedulingCapabilities
    from app.agent.specialized.scheduling_graph import build_scheduling_graph

    graph = build_scheduling_graph(SchedulingCapabilities(context))
    final = await graph.ainvoke({}, config={"recursion_limit": 40})
    return final["result"]


def executors() -> dict:
    return {("order_intake", GRAPH_VERSION): execute_order, ("scheduling", GRAPH_VERSION): execute_scheduling}
