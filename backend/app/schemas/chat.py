from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.order import OrderDraftCreate


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    message_count: int = 0


class ChatAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mime_type: Literal["image/jpeg", "image/png"]
    byte_size: int


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
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str = Field(default="", max_length=10000)
    session_id: str
    image_data_url: str | None = None

    @model_validator(mode="after")
    def require_content_or_image(self):
        if not self.content.strip() and not self.image_data_url:
            raise ValueError("消息或图片至少提供一项")
        return self


class ConfirmRequest(BaseModel):
    session_id: str


class OrderWorkspaceDraft(OrderDraftCreate):
    pass


class OrderWorkspaceDraftRequest(BaseModel):
    session_id: str
    draft: OrderWorkspaceDraft


class OrderConfirmRequest(ConfirmRequest):
    order_draft: OrderWorkspaceDraft | None = None


class WorkspaceStateOut(BaseModel):
    active_workspace: Literal["order_form", "schedule_plan"] | None = None
    order_draft: OrderWorkspaceDraft | None = None
    schedule_plan: dict[str, Any] | None = None
