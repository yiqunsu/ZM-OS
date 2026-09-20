"""Strict public input contracts for the specialized Agent API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateSession(AgentInput):
    agent_type: Literal["ORDER_INTAKE", "SCHEDULING"]
    title: str | None = Field(default=None, min_length=1, max_length=120)


class SendMessage(AgentInput):
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(default="", max_length=10000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    expected_state_revision: int = Field(gt=0)
    target_work_item_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def valid_input(self):
        if not self.content and not self.attachment_ids:
            raise ValueError("请输入文字或上传订单截图")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("附件不能重复")
        if any(not value or len(value) > 128 for value in self.attachment_ids):
            raise ValueError("附件ID无效")
        return self


class SessionAction(AgentInput):
    expected_state_revision: int = Field(gt=0)
