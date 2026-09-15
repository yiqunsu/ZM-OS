"""Explicit response projections; no authorization, mutations or transaction ownership."""

from app.models import AgentRun, ChatMessage, ChatSession, OrderIntakeItem


def item_snapshot(item: OrderIntakeItem) -> dict:
    snapshot = {
        name: getattr(item, name)
        for name in (
            "id",
            "session_id",
            "source_message_id",
            "source_attachment_id",
            "queue_position",
            "source_order_index",
            "status",
            "revision",
            "recognition_status",
            "draft",
            "issues",
            "order_id",
            "last_error_code",
            "created_at",
        )
    }

    # Retired policy warnings must not mislead users reopening an existing draft.
    snapshot["issues"] = [
        issue for issue in (item.issues or []) if issue.get("code") != "WEIGHT_CONVERSION_UNAVAILABLE"
    ]
    return snapshot


def session_dto(session: ChatSession) -> dict:
    return {
        name: getattr(session, name)
        for name in (
            "id",
            "agent_type",
            "status",
            "title",
            "state_schema_version",
            "state_revision",
            "state",
            "active_work_item_id",
            "active_plan_id",
            "last_event_seq",
            "created_at",
            "updated_at",
        )
    }


def run_dto(run: AgentRun) -> dict:
    return {
        name: getattr(run, name)
        for name in (
            "id",
            "session_id",
            "status",
            "outcome",
            "trigger_kind",
            "trigger_message_id",
            "work_item_id",
            "retry_of_run_id",
            "output_message_id",
            "error_code",
            "error_message",
            "queued_at",
            "started_at",
            "finished_at",
        )
    }


def message_dto(message: ChatMessage) -> dict:
    return {
        name: getattr(message, name)
        for name in (
            "id",
            "session_id",
            "role",
            "origin",
            "content",
            "presentation",
            "run_id",
            "command_id",
            "work_item_id",
            "event_seq",
            "created_at",
        )
    }


def accepted_dto(message: ChatMessage, run: AgentRun, items: list[OrderIntakeItem], revision: int) -> dict:
    return {
        "message_id": message.id,
        "run_id": run.id,
        "run_status": "QUEUED",
        "work_item_ids": [item.id for item in items],
        "state_revision": revision,
        "event_cursor": message.event_seq,
    }
