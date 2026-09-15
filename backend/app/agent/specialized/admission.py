"""Validate routing decisions independently from optional model explanations."""

from typing import Literal

from fastapi import HTTPException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.errors import AdmissionResponseError
from app.agent.model_transport import content_text, parse_json_object
from app.schemas.agent import AgentInput


class Admission(AgentInput):
    decision: Literal["ALLOW", "CLARIFY", "OUT_OF_SCOPE"]
    reason_code: Literal["IN_SCOPE", "NEEDS_TARGET", "MISSING_INPUT", "WRONG_AGENT", "UNSUPPORTED_OPERATION"]
    requested_operation: Literal[
        "QUERY", "EXPLAIN_DRAFT", "GENERATE", "EXECUTE_REQUEST", "ADJUST_REQUEST"
    ] = "QUERY"


def parse_admission(reply: AIMessage) -> Admission:
    # An incomplete response must never authorize a graph, even if it parses as JSON.
    if reply.response_metadata.get("finish_reason") in {"length", "content_filter"} or reply.tool_calls:
        raise AdmissionResponseError()
    try:
        result = parse_json_object(content_text(reply.content))
        # A known explanatory field is not a routing instruction or an audit fact.
        # Keep all decision fields and all other unexpected fields strictly validated.
        result.pop("reason", None)
        return Admission.model_validate(result)
    except (HTTPException, ValidationError) as err:
        raise AdmissionResponseError() from err
