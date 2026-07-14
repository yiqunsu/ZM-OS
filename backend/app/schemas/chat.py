from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    message_count: int = 0


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str | None = None
    role: str
    content: str | None = None
    tool_calls: dict | list | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_pending: bool
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str
    session_id: str


class ConfirmRequest(BaseModel):
    session_id: str
