"""Append-only events; callers hold the Session lock and own the transaction."""

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, SessionEvent
from app.models.agent import EVENT_KINDS
from app.models.base import generate_id


class MessageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    text: str = Field(max_length=20000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def append_event(
    db: AsyncSession,
    session: ChatSession,
    kind: str,
    payload: dict,
    *,
    actor_kind: str = "SYSTEM",
    actor_user_id: str | None = None,
    run_id: str | None = None,
    message_id: str | None = None,
    command_id: str | None = None,
    work_item_id: str | None = None,
    tool_call_id: str | None = None,
) -> SessionEvent:
    if kind not in EVENT_KINDS:
        raise ValueError("unregistered event kind")
    if kind in {"message.accepted", "message.completed"}:
        payload = MessageSnapshot.model_validate(payload).model_dump()
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 131072:
        raise ValueError("event payload too large")
    session.last_event_seq += 1
    session.updated_at = datetime.now(UTC)
    event = SessionEvent(
        id=generate_id(),
        session_id=session.id,
        seq=session.last_event_seq,
        kind=kind,
        schema_version=1,
        payload=payload,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        run_id=run_id,
        message_id=message_id,
        command_id=command_id,
        work_item_id=work_item_id,
        tool_call_id=tool_call_id,
    )
    db.add(event)
    return event


def event_dto(event: SessionEvent) -> dict:
    return {
        name: getattr(event, name)
        for name in (
            "id",
            "session_id",
            "seq",
            "kind",
            "schema_version",
            "actor_kind",
            "run_id",
            "message_id",
            "command_id",
            "work_item_id",
            "tool_call_id",
            "payload",
            "created_at",
        )
    }
